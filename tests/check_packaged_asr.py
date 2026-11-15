"""Exercise extracted private runtimes against loopback-only OpenAI wire fixtures.

Uses an OS-assigned loopback proxy port and disposable service data.
No real upstream or API key is used. Service configuration uses public APIs only.
"""

import argparse
import asyncio
import base64
import datetime
import hashlib
import io
import json
import math
import os
import platform
import socket
import ssl
import struct
import tempfile
import wave
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.openai.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.openai.com")]), False)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = directory / "fixture.pem", directory / "fixture-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    return context, cert_file


async def check(args, report):
    source = struct.pack("<16007h", *(round(10000 * math.sin(2 * math.pi * 1000 * n / 16000))
                                     for n in range(16007)))
    wire, tunnels = [], set()

    async def realtime(request):
        assert request.headers["Authorization"] == "Bearer fictional-packaged-key"
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        update = await ws.receive_json()
        config = update["session"]
        assert config["audio"]["input"]["format"]["rate"] == 24000
        assert config["audio"]["input"]["turn_detection"] is None
        await ws.send_json({"type": "session.updated", "session": config})
        audio, appends = bytearray(), 0
        async for message in ws:
            event = json.loads(message.data)
            if event["type"] == "input_audio_buffer.append":
                audio.extend(base64.b64decode(event["audio"], validate=True))
                appends += 1
                if appends == 1:
                    await ws.send_json({"type": "conversation.item.input_audio_transcription.delta",
                                        "item_id": "turn", "content_index": 0, "delta": "预览"})
            elif event["type"] == "input_audio_buffer.commit":
                samples = struct.unpack("<" + str(len(audio) // 2) + "h", audio)
                assert abs(len(samples) - 16007 * 1.5) <= 1
                rms = math.sqrt(sum(value * value for value in samples) / len(samples))
                assert 6900 < rms < 7200 and appends > 1
                wire.append({"path": "realtime", "samples24k": len(samples), "rms": rms,
                             "sha256": hashlib.sha256(audio).hexdigest(), "appends": appends})
                await ws.send_json({"type": "input_audio_buffer.committed", "item_id": "turn",
                                    "previous_item_id": None})
                await ws.send_json({"type": "conversation.item.input_audio_transcription.completed",
                                    "item_id": "turn", "content_index": 0, "transcript": "定稿。",
                                    "usage": {"type": "duration", "seconds": 1.001}})
            else:
                raise AssertionError("unexpected fixture control")
        return ws

    async def file(request):
        assert request.headers["Authorization"] == "Bearer fictional-packaged-key"
        multipart, fields = await request.multipart(), {}
        while part := await multipart.next():
            fields[part.name] = await part.read()
        with wave.open(io.BytesIO(fields["file"]), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            assert wav.readframes(wav.getnframes()) == source
        streamed = fields.get("stream") == b"true"
        wire.append({"path": "file-sse" if streamed else "file-json", "sourceSamples": len(source) // 2})
        usage = {"type": "duration", "seconds": 1.001}
        if not streamed:
            return web.json_response({"text": "定稿。", "usage": usage})
        events = [{"type": "transcript.text.delta", "delta": "预览"},
                  {"type": "transcript.text.done", "text": "定稿。", "usage": usage}]
        body = "".join("data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events)
        return web.Response(text=body, content_type="text/event-stream")

    with tempfile.TemporaryDirectory(prefix="runtime-", dir=args.results) as temporary:
        directory = Path(temporary)
        tls, cert = certificate(directory)
        upstream = web.Application()
        upstream.router.add_get("/v1/realtime", realtime)
        upstream.router.add_post("/v1/audio/transcriptions", file)
        backend = TestServer(upstream, scheme="https")
        await backend.start_server(ssl=tls)
        async with backend:
            async def tunnel(reader, writer):
                task, remote, pumps = asyncio.current_task(), None, []
                tunnels.add(task)
                try:
                    header = await reader.readuntil(b"\r\n\r\n")
                    assert header.split(b"\r\n", 1)[0] == b"CONNECT api.openai.com:443 HTTP/1.1"
                    report["proxyConnections"] += 1
                    incoming, remote = await asyncio.open_connection("127.0.0.1", backend.port)
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()

                    async def pump(src, dst):
                        while chunk := await src.read(65536):
                            dst.write(chunk)
                            await dst.drain()

                    pumps = [asyncio.create_task(pump(reader, remote)), asyncio.create_task(pump(incoming, writer))]
                    await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for pump_task in pumps:
                        pump_task.cancel()
                    await asyncio.gather(*pumps, return_exceptions=True)
                    for stream in (remote, writer):
                        if stream:
                            stream.close()
                    await asyncio.gather(*(stream.wait_closed() for stream in (remote, writer) if stream),
                                         return_exceptions=True)
                    tunnels.discard(task)

            proxy = await asyncio.start_server(tunnel, "127.0.0.1", 0)
            proxy_port = proxy.sockets[0].getsockname()[1]
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            env = {key: value for key, value in os.environ.items() if not key.startswith(("OPENASR", "PYTHON"))}
            env.update(HOME=str(directory), SSL_CERT_FILE=str(cert), OPENASR_DATA_ROOT=str(directory / "root"))
            command = [str(args.runtime)] + (["-m", "openasrportal"] if args.python_runtime else [])
            command += ["--host", "127.0.0.1", "--port", str(port), "--data-dir", str(directory / "data")]
            with (args.results / "runtime.log").open("w") as log:
                child = await asyncio.create_subprocess_exec(*command, env=env, cwd=directory,
                                                              stdout=log, stderr=log)
                try:
                    async with proxy, aiohttp.ClientSession(trust_env=False) as client:
                        base = f"http://127.0.0.1:{port}"

                        async def api(method, path, body=None, token=""):
                            async with client.request(method, base + path, json=body,
                                                      headers={"Authorization": "Bearer " + token}) as response:
                                result = await response.json()
                                assert response.status < 400, result
                                return result

                        deadline = asyncio.get_running_loop().time() + 90
                        while True:
                            try:
                                await api("GET", "/health")
                                break
                            except (aiohttp.ClientError, OSError):
                                if child.returncode is not None or asyncio.get_running_loop().time() >= deadline:
                                    raise RuntimeError("packaged service startup failed") from None
                                await asyncio.sleep(.1)
                        status = await api("GET", "/v1/admin/auth/status")
                        password = "Fictional package administrator 2026!"
                        admin = (await api("POST", "/v1/admin/auth/setup", {
                            "password": password, "confirmPassword": password,
                            "setupChallenge": status["setupChallenge"]}))["token"]
                        key = (await api("POST", "/v1/admin/asr-keys", {"title": "package-fixture"}, admin))["key"]
                        await api("PATCH", "/v1/admin/settings", {"proxy": {"url": f"http://127.0.0.1:{proxy_port}"}}, admin)
                        for mode in ("realtime", "json", "sse"):
                            provider = "openai_realtime" if mode == "realtime" else "openai_file"
                            config = {"apiKey": "fictional-packaged-key", "useProxy": True}
                            if mode != "realtime":
                                config["responseMode"] = mode
                            await api("POST", "/v1/admin/profiles", {"id": mode, "title": mode,
                                      "provider": provider, "configuration": config}, admin)
                            session = await api("POST", "/v1/sessions", {"profileId": mode,
                                                "requiredFeatures": ["effectiveSessionLimits"]}, key)
                            events = []
                            async with client.ws_connect(base + session["streamPath"] + "?ticket=" + session["ticket"]) as ws:
                                ready = await ws.receive_json(timeout=60)
                                assert ready["type"] == "session.ready", ready
                                for offset in range(0, len(source), 2048):
                                    await ws.send_bytes(source[offset:offset + 2048])
                                await ws.send_json({"type": "audio.end"})
                                while True:
                                    event = await ws.receive_json(timeout=60)
                                    events.append(event)
                                    if event["type"].startswith("session."):
                                        break
                            assert events[-1]["type"] == "session.finished", events
                            assert events[-1]["acceptedAudioSamples"] == events[-1]["submittedAudioSamples"] == 16007
                            assert [event["text"] for event in events if event["type"] == "transcript.final"] == ["定稿。"]
                            report["workflows"].append({"mode": mode, "passed": True})
                        report["wire"] = wire
                        assert len(wire) == report["proxyConnections"] == 3
                finally:
                    if child.returncode is None:
                        child.terminate()
                        await asyncio.wait_for(child.wait(), 30)
                    proxy.close()
                    await proxy.wait_closed()
                    if tunnels:
                        await asyncio.wait_for(asyncio.gather(*list(tunnels)), 10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--python-runtime", action="store_true")
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    args.runtime, args.results = args.runtime.resolve(), args.results.resolve()
    args.results.mkdir(parents=True, exist_ok=False)
    report = {"scope": "packaged runtime, simulated upstream, no real ASR or installer acceptance",
              "platform": platform.platform(), "runtimeSha256": hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
              "proxyConnections": 0, "workflows": [], "passed": False}
    try:
        asyncio.run(check(args, report))
        report["passed"] = True
    finally:
        (args.results / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS packaged ASR: native SoXR conversion/flush, source WAV JSON/SSE, explicit CONNECT proxy")


if __name__ == "__main__":
    main()
