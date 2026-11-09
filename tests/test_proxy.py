"""Real local CONNECT/TLS transports; no cloud credentials or production data."""

import asyncio
import base64
import datetime
import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from support_auth import fixture_token, portal_for_tests
from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.providers import transport
from openasrportal.storage.store import Store


class ProxyStorageTests(unittest.TestCase):
    def test_persistence_redaction_validation_and_credential_rotation(self):
        with tempfile.TemporaryDirectory(dir="test-results") as directory:
            store = Store(directory)
            value = {"url": "https://proxy.example:8443", "username": "test-user",
                     "password": "fictional-proxy-secret"}
            store.proxy.save(value)
            store.save("local", "Local", "openlocalasr", {"apiKey": "key", "useProxy": True})
            restored = Store(directory)
            self.assertEqual(restored.proxy.runtime(), value)
            self.assertTrue(restored.get("local")["configuration"]["useProxy"])
            self.assertNotIn("proxy", restored.settings())
            public = json.dumps(restored.settings(admin=True))
            self.assertNotIn(value["password"], public)
            self.assertNotIn(value["username"], public)
            self.assertNotIn(value["password"].encode(), restored.path.read_bytes())
            for bad in ("socks5://proxy:80", "http://user:password@proxy:80", "http://proxy/path",
                        "http://proxy:0", "http://proxy:99999", "http://proxy\n", None):
                with self.assertRaises(ValueError):
                    restored.proxy.save({"url": bad})
                self.assertEqual(restored.proxy.runtime(), value)
            with self.assertRaises(ValueError):
                restored.save("local", "Local", "openlocalasr", {"useProxy": "true"})
            restored.proxy.save({"url": value["url"]})
            self.assertEqual(restored.proxy.runtime(), value)
            restored.proxy.save({"url": "http://other.example:8080"})
            self.assertFalse(restored.proxy.public()["hasCredentials"])
            restored.proxy.save(value)
            restored.proxy.save({"username": "", "password": ""})
            self.assertFalse(restored.proxy.public()["hasCredentials"])
            restored.proxy.save(value)
            restored.proxy.save({"url": ""})
            self.assertEqual(restored.proxy.runtime(), {"url": ""})


def tls_contexts(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = Path(directory) / "cert.pem", Path(directory) / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, key_path)
    return server, ssl.create_default_context(cafile=str(cert_path))


class ProxyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="test-results")
        self.tls, self.trust = tls_contexts(self.directory.name)
        self.requests, self.upstream_headers, self.tasks = [], [], set()
        self.release = asyncio.Event()
        self.seen = asyncio.Event()
        self.status = 200
        self.stall = False

        async def echo(ws, path):
            self.upstream_headers.append(dict(ws.request_headers))
            async for message in ws:
                await ws.send(message)

        self.upstream = await serve(echo, "127.0.0.1", 0, ssl=self.tls)
        port = self.upstream.sockets[0].getsockname()[1]
        self.endpoint = f"wss://localhost:{port}/recognize"
        self.target_port = port
        self.sessions = []
        original = aiohttp.ClientSession

        def session(**kwargs):
            result = original(connector=aiohttp.TCPConnector(ssl=self.trust), **kwargs)
            self.sessions.append(result)
            return result

        self.patcher = patch.object(transport.aiohttp, "ClientSession", session)
        self.patcher.start()

    async def tunnel(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        remote = None
        pumps = []
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            self.requests.append(headers.decode())
            self.seen.set()
            if self.stall:
                await reader.read()
                return
            if self.status != 200:
                writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            upstream, remote = await asyncio.open_connection("127.0.0.1", self.target_port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def pump(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            pumps = [asyncio.create_task(pump(reader, remote)),
                     asyncio.create_task(pump(upstream, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pump_task in pumps:
                pump_task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (remote, writer):
                if stream:
                    stream.close()
            self.tasks.discard(task)

    async def asyncTearDown(self):
        self.release.set()
        for session in self.sessions:
            self.assertTrue(session.closed, "proxy session leaked")
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.upstream.close()
        await self.upstream.wait_closed()
        self.patcher.stop()
        self.directory.cleanup()

    async def test_http_and_https_connect_authentication_and_frames(self):
        for scheme in ("http", "https"):
            proxy = await asyncio.start_server(self.tunnel, "127.0.0.1", 0,
                                               ssl=self.tls if scheme == "https" else None)
            async with proxy:
                port = proxy.sockets[0].getsockname()[1]
                socket = await transport.connect(self.endpoint, use_proxy=True,
                    proxy={"url": f"{scheme}://localhost:{port}", "username": "test-user",
                           "password": "test-password"},
                    extra_headers={"Authorization": "Bearer upstream-only"})
                try:
                    for frame in (bytes(6400), '{"type":"keepalive"}', ""):
                        await socket.send(frame)
                        self.assertEqual(await socket.recv(), frame)
                finally:
                    await socket.close()
            self.assertTrue(self.requests[-1].startswith(f"CONNECT localhost:{self.target_port} "))
            auth = base64.b64encode(b"test-user:test-password").decode()
            self.assertIn("Proxy-Authorization: Basic " + auth, self.requests[-1])
            self.assertNotIn("upstream-only", self.requests[-1])
            self.assertNotIn("proxy-authorization", self.upstream_headers[-1])
            self.assertEqual(self.upstream_headers[-1]["authorization"], "Bearer upstream-only")

    async def test_rejection_missing_proxy_timeout_and_cancellation_never_fall_back(self):
        with patch.object(transport, "direct_connect", AsyncMock()) as direct:
            with self.assertRaises(ProviderError):
                await transport.connect(self.endpoint, use_proxy=True)
            self.status = 407
            proxy = await asyncio.start_server(self.tunnel, "127.0.0.1", 0)
            async with proxy:
                value = {"url": f"http://localhost:{proxy.sockets[0].getsockname()[1]}"}
                with self.assertRaisesRegex(ProviderError, "代理连接或认证失败"):
                    await transport.connect(self.endpoint, use_proxy=True, proxy=value)
                self.stall = True
                with self.assertRaises(asyncio.TimeoutError):
                    await transport.connect(self.endpoint, use_proxy=True, proxy=value, open_timeout=.05)
                self.seen.clear()
                task = asyncio.create_task(transport.connect(self.endpoint, use_proxy=True, proxy=value))
                await self.seen.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            direct.assert_not_called()

    async def test_direct_ignores_environment_proxy(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1"}):
            socket = await transport.connect(self.endpoint, ssl=self.trust)
            try:
                await socket.send("direct")
                self.assertEqual(await socket.recv(), "direct")
            finally:
                await socket.close()
        self.assertEqual(self.requests, [])

    async def test_public_probe_and_recognition_use_selected_proxy(self):
        async def upstream(ws):
            start = json.loads(await ws.recv())
            task_id = start["header"]["task_id"]
            async def event(kind, payload=None):
                await ws.send(json.dumps({"header": {"event": kind, "task_id": task_id},
                                          "payload": payload or {}}))
            await event("task-started")
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                await event("result-generated", {"output": {"sentence": {
                    "sentence_id": 1, "text": "代理测试。", "sentence_end": True,
                    "begin_time": 0, "end_time": 200,
                }}})
                await event("task-finished")
                return

        async with serve(upstream, "127.0.0.1", 0, ssl=self.tls) as backend:
            self.target_port = backend.sockets[0].getsockname()[1]
            proxy = await asyncio.start_server(self.tunnel, "127.0.0.1", 0)
            async with proxy:
                store = Store(Path(self.directory.name) / "portal")
                store.proxy.save({"url": f"http://localhost:{proxy.sockets[0].getsockname()[1]}"})
                store.save("local", "Local", "openlocalasr", {
                    "apiKey": "fictional-key", "useProxy": True,
                    "endpoint": f"wss://localhost:{self.target_port}/api-ws/v1/inference",
                })
                portal = portal_for_tests(store, "client-key", "admin-key")
                server = TestServer(portal.app())
                await server.start_server()
                try:
                    async with aiohttp.ClientSession() as client:
                        admin = {"Authorization": "Bearer " + fixture_token(portal, "admin-key")}
                        async with client.post(server.make_url("/v1/admin/profiles/local/test"),
                                               headers=admin) as response:
                            self.assertTrue((await response.json())["ok"])
                        self.assertEqual(len(self.requests), 1)
                        async with client.post(server.make_url("/v1/sessions"), json={"profileId": "local"},
                                               headers={"Authorization": "Bearer client-key"}) as response:
                            session = await response.json()
                        url = server.make_url(session["streamPath"] + "?ticket=" + session["ticket"])
                        async with client.ws_connect(url) as ws:
                            self.assertEqual((await ws.receive_json())["type"], "session.ready")
                            await ws.send_bytes(bytes(6400))
                            await ws.send_json({"type": "audio.end"})
                            events = []
                            while True:
                                event = await asyncio.wait_for(ws.receive_json(), 5)
                                events.append(event)
                                if event["type"] == "session.finished":
                                    break
                            self.assertEqual(sum(event["type"] == "transcript.final" for event in events), 1)
                        self.assertEqual(len(self.requests), 2)
                finally:
                    await server.close()
