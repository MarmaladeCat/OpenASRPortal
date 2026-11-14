"""远程协议、分句去重与本机模拟 WebSocket 双向桥接；不访问云服务。"""

import asyncio
import gzip
import json
import struct
import tempfile
import unittest
from pathlib import Path

try:
    from websockets.legacy.client import connect
    from websockets.legacy.server import serve
except ImportError:
    raise unittest.SkipTest("远程 ASR 测试需要 websockets==13.1")

from openasrportal.domain.config import BAILIAN_MODEL, DOUBAO_MODEL, validate_config
from openasrportal.domain.management import contract
from openasrportal.providers.doubao_asr import (
    DoubaoProvider,
    ProviderError,
    ResultNormalizer,
    decode_packet,
    encode_packet,
)
from openasrportal.providers.legacy import bridge
from openasrportal.storage.store import Store


def utterance(text, start, end, definite):
    return {"text": text, "start_time": start, "end_time": end, "definite": definite}


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_prebuffer_and_end_are_paced_without_idle_credit(self):
        times = []

        class Socket:
            async def send(self, packet):
                times.append(asyncio.get_running_loop().time())

        provider = DoubaoProvider({})
        provider.socket = Socket()
        for _ in range(3):
            await provider.send_audio(bytes(6400))
        await provider.send_audio(b"", last=True)
        self.assertEqual(provider.sequence, 5)
        self.assertTrue(all(b - a >= .19 for a, b in zip(times, times[1:])))


class ProtocolTests(unittest.TestCase):
    def test_silence_boundaries_defaults_and_independent_bailian_range(self):
        default = validate_config(DOUBAO_MODEL, {"apiKey": "fictional"})
        self.assertEqual(default["silenceMs"], 5000)
        self.assertFalse(default["enableNonstream"])
        for silence in (300, 800, 5000):
            self.assertEqual(validate_config(DOUBAO_MODEL, {"silenceMs": silence}, default)["silenceMs"], silence)
        for silence in (200, 299, 5001, 6000, True, 800.0, "800"):
            with self.subTest(silence=silence), self.assertRaises(ValueError):
                validate_config(DOUBAO_MODEL, {"silenceMs": silence}, default)
        for silence in (200, 6000):
            self.assertEqual(validate_config(BAILIAN_MODEL, {"apiKey": "fictional", "silenceMs": silence})["silenceMs"], silence)
        definition = next(p for p in contract()["providers"] if p["id"] == DOUBAO_MODEL)
        field = next(f for f in definition["fields"] if f["key"] == "silenceMs")
        self.assertEqual((field["min"], field["max"], field["default"]), (300, 5000, 5000))

    def test_stored_silence_migration_retains_keys_switches_and_valid_values(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "test-results") as directory:
            store = Store(directory)
            for old, expected in ((200, 300), (299, 300), (800, 800), (5000, 5000), (6000, 5000)):
                for enabled in (False, True):
                    saved = {"apiKey": "fictional", "silenceMs": old, "enableNonstream": enabled}
                    store.save("doubao", "Doubao", DOUBAO_MODEL, {"apiKey": "fictional"})
                    with store.connection() as db:
                        db.execute("UPDATE profiles SET configuration=? WHERE id='doubao'", (json.dumps(saved),))
                    migrated = store.get("doubao")["configuration"]
                    self.assertEqual(migrated, {**saved, "silenceMs": expected})
                    self.assertEqual(store.list()[0]["configuration"]["silenceMs"], expected)
                    store.save("doubao", "Doubao", DOUBAO_MODEL, {})
                    reopened = Store(directory).get("doubao")["configuration"]
                    self.assertEqual((reopened["silenceMs"], reopened["enableNonstream"], reopened["apiKey"]),
                                     (expected, enabled, "fictional"))

    def test_terminal_flag_never_promotes_or_erases_unstable_text(self):
        pending = utterance("不应提交", 0, 400, False)
        for terminal in ({"result": {"utterances": [pending]}}, {"result": {}}, {"result": {"utterances": []}}):
            with self.subTest(terminal=terminal):
                normalizer = ResultNormalizer()
                normalizer.accept({"result": {"utterances": [pending]}})
                with self.assertRaises(ProviderError):
                    normalizer.accept(terminal, last=True)
                self.assertEqual(normalizer.results.results["window:0"].text, "不应提交")
                self.assertEqual(normalizer.committed, [])
        with self.assertRaises(ProviderError):
            ResultNormalizer().accept({"result": {"utterances": [pending]}}, last=True)
        self.assertEqual(ResultNormalizer().accept({"result": {}}, last=True), [])

    def test_signed_last_audio_and_error_frames(self):
        pcm = bytes(range(256)) * 25
        raw = encode_packet(2, 12, pcm, last=True)
        self.assertEqual(raw[:4], bytes([0x11, 0x23, 0x11, 0]))
        seq, size = struct.unpack(">iI", raw[4:12])
        self.assertEqual(seq, -12)
        self.assertEqual(size, len(raw) - 12)
        self.assertEqual(gzip.decompress(raw[12:]), pcm)
        secret_body = b'{"message":"do not expose request credentials"}'
        error = (
            bytes([0x11, 0xF0, 0x10, 0])
            + struct.pack(">II", 45000001, len(secret_body))
            + secret_body
        )
        with self.assertRaisesRegex(ProviderError, "45000001") as raised:
            decode_packet(error)
        self.assertNotIn("credentials", str(raised.exception))
        for invalid in (b"", b"\x11\x90\x11\0\0\0\0\x10", "text"):
            with self.assertRaises(ProviderError):
                decode_packet(invalid)

    def test_repeated_finals_and_partial_corrections_do_not_duplicate_text(self):
        normalizer = ResultNormalizer()
        first = utterance("开放时间。", 100, 800, True)
        pending = utterance("早上就点", 1100, 1900, False)
        events = normalizer.accept({"result": {"utterances": [first, pending]}})
        self.assertEqual(
            [(e.stable, e.text) for e in events],
            [(True, "开放时间。"), (False, "早上就点")],
        )
        pending["text"] = "早上9点。"
        events = normalizer.accept({"result": {"utterances": [first, pending]}})
        self.assertEqual([e.text for e in events], ["早上9点。"])
        pending["definite"] = True
        events = normalizer.accept({"result": {"utterances": [first, pending]}})
        self.assertEqual([e.stable for e in events], [True])
        self.assertEqual(events[0].start_ms, 1100)
        self.assertEqual(normalizer.accept({"result": {"utterances": [first, pending]}}, True), [])

    def test_second_pass_replaces_stream_hypothesis_before_commit(self):
        normalizer = ResultNormalizer()
        stream = {
            **utterance("我们在公园开会", 100, 1800, False),
            "additions": {"source": "stream"},
        }
        events = normalizer.accept({"result": {"utterances": [stream]}})
        self.assertEqual([event.stable for event in events], [False])
        self.assertEqual(events[0].start_ms, 100)
        corrected = {
            **utterance("我们在公司开会。", 100, 1900, True),
            "additions": {"source": "two_pass"},
        }
        events = normalizer.accept({"result": {"utterances": [corrected]}})
        self.assertTrue(events[0].stable)
        self.assertEqual(events[0].text, "我们在公司开会。")
        self.assertEqual(events[0].source, "two_pass")
        self.assertEqual(normalizer.accept({"result": {"utterances": [corrected]}}, True), [])


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_pass_controls_upstream_endpoint_without_cutting_audio(self):
        for settings, window in (({}, None), ({"enableNonstream": False, "silenceMs": 800}, None),
                                 ({"enableNonstream": True}, 5000),
                                 ({"enableNonstream": True, "silenceMs": 1200}, 1200)):
            with self.subTest(settings=settings):
                received = []
                request = {}

                async def upstream(socket):
                    initial = await socket.recv()
                    request.update(json.loads(gzip.decompress(initial[12:]))["request"])
                    await socket.send(encode_packet(9, 1, b'{"result":{}}'))
                    async for raw in socket:
                        received.append(gzip.decompress(raw[12:]))
                        if raw[1] & 2:
                            await socket.send(encode_packet(9, 2, b'{"result":{}}', last=True))
                            break

                config = validate_config(DOUBAO_MODEL, {"apiKey": "fictional", **settings})
                async with serve(upstream, "127.0.0.1", 0) as cloud:
                    config["endpoint"] = "ws://127.0.0.1:%s" % cloud.sockets[0].getsockname()[1]
                    provider = DoubaoProvider(config)
                    audio = b"\x01\x00" * 3200 + bytes(96000) + b"\x02\x00" * 3200
                    try:
                        await provider.open()
                        await provider.send_audio(audio)
                        await provider.send_audio(b"", last=True)
                        _, last = await provider.receive()
                        self.assertTrue(last)
                    finally:
                        await provider.close()
                self.assertEqual(b"".join(received), audio)
                self.assertEqual(request["enable_nonstream"], settings.get("enableNonstream", False))
                if window is None:
                    self.assertNotIn("end_window_size", request)
                else:
                    self.assertEqual(request["end_window_size"], window)

    async def test_streams_pcm_and_normalizes_interim_final_and_end(self):
        received, requests = [], []
        partial = utterance("你好", 0, 200, False)
        final = utterance("你好。", 0, 400, True)

        async def upstream(socket):
            requests.append(dict(socket.request_headers))
            initial = await socket.recv()
            payload = json.loads(gzip.decompress(initial[12:]))
            self.assertEqual(payload["audio"]["rate"], 16000)
            self.assertEqual(
                json.loads(payload["request"]["corpus"]["context"]),
                {"hotwords": [{"word": "麒麟"}]},
            )
            await socket.send(encode_packet(9, 1, b'{"result":{}}'))
            async for raw in socket:
                received.append(gzip.decompress(raw[12:]))
                last = bool(raw[1] & 2)
                item = final if last else partial
                payload = json.dumps({"result": {"utterances": [item]}}).encode()
                await socket.send(encode_packet(9, 2, payload, last=last))
                if last:
                    self.assertLess(struct.unpack(">i", raw[4:8])[0], 0)
                    break

        async with serve(upstream, "127.0.0.1", 0) as upstream_server:
            config = {
                "endpoint": "ws://127.0.0.1:%s" % upstream_server.sockets[0].getsockname()[1],
                "apiKey": "unit-test-key",
                "resourceId": "volc.seedasr.sauc.duration",
                "enableNonstream": True,
                "hotwords": [{"text": "麒麟", "weight": 4}],
            }

            async def handler(socket):
                await bridge(socket, DoubaoProvider(config))

            async with serve(handler, "127.0.0.1", 0) as runtime:
                async with connect(
                    "ws://127.0.0.1:%s" % runtime.sockets[0].getsockname()[1]
                ) as client:
                    await client.send('{"signal":"start"}')
                    ready = json.loads(await client.recv())
                    self.assertEqual(ready["type"], "server_ready")
                    self.assertEqual(ready["text_processing"], "native")
                    # 与麦克风不同长度的包输入，适配层聚合为 200ms 包并保留最后不足一包的音频。
                    await client.send(bytes(3200))
                    await client.send(bytes(4000))
                    interim = json.loads(await asyncio.wait_for(client.recv(), 2))
                    self.assertEqual(interim["nbest"][0]["sentence"], "你好")
                    await client.send('{"signal":"end"}')
                    events = []
                    async for raw in client:
                        events.append(json.loads(raw))
                    self.assertEqual(
                        [e["type"] for e in events],
                        ["final_result", "speech_end"],
                    )
                    self.assertEqual(events[0]["nbest"][0]["sentence"], "你好。")
        self.assertEqual([len(p) for p in received], [6400, 800, 0])
        self.assertEqual(requests[0]["x-api-key"], "unit-test-key")
        self.assertNotIn("authorization", requests[0])

    async def test_provider_failure_reaches_client_and_releases_provider(self):
        class Rejected:
            closed = False

            async def open(self):
                raise ProviderError("测试鉴权失败（HTTP 403）")

            async def close(self):
                self.closed = True

        provider = Rejected()

        async def handler(socket):
            await bridge(socket, provider)

        async with serve(handler, "127.0.0.1", 0) as runtime:
            async with connect("ws://127.0.0.1:%s" % runtime.sockets[0].getsockname()[1]) as client:
                await client.send('{"signal":"start"}')
                error = json.loads(await client.recv())
                self.assertEqual(error["status"], "failed")
                self.assertIn("403", error["message"])
                await client.wait_closed()
        self.assertTrue(provider.closed)

    async def test_upstream_disconnect_is_reported_instead_of_silent_success(self):
        async def upstream(socket):
            await socket.recv()
            await socket.send(encode_packet(9, 1, b'{"result":{}}'))
            await socket.close(code=1011)

        async with serve(upstream, "127.0.0.1", 0) as cloud:
            config = {
                "endpoint": "ws://127.0.0.1:%s" % cloud.sockets[0].getsockname()[1],
                "apiKey": "test",
                "resourceId": "test",
                "enableNonstream": True,
            }

            async def handler(client):
                await bridge(client, DoubaoProvider(config))

            async with serve(handler, "127.0.0.1", 0) as runtime:
                async with connect(
                    "ws://127.0.0.1:%s" % runtime.sockets[0].getsockname()[1]
                ) as client:
                    await client.send('{"signal":"start"}')
                    events = [json.loads(raw) async for raw in client]
                    self.assertEqual(events[0]["type"], "server_ready")
                    self.assertEqual(events[-1]["status"], "failed")
                    self.assertFalse(any(e.get("type") == "speech_end" for e in events))

    async def test_client_disconnect_closes_cloud_connection(self):
        closed = asyncio.Event()

        async def upstream(socket):
            await socket.recv()
            await socket.send(encode_packet(9, 1, b'{"result":{}}'))
            await socket.wait_closed()
            closed.set()

        async with serve(upstream, "127.0.0.1", 0) as cloud:
            config = {
                "endpoint": "ws://127.0.0.1:%s" % cloud.sockets[0].getsockname()[1],
                "apiKey": "test",
                "resourceId": "test",
                "enableNonstream": True,
            }

            async def handler(client):
                await bridge(client, DoubaoProvider(config))

            async with serve(handler, "127.0.0.1", 0) as runtime:
                async with connect(
                    "ws://127.0.0.1:%s" % runtime.sockets[0].getsockname()[1]
                ) as client:
                    await client.send('{"signal":"start"}')
                    self.assertEqual(json.loads(await client.recv())["type"], "server_ready")
                await asyncio.wait_for(closed.wait(), 2)


if __name__ == "__main__":
    unittest.main()
