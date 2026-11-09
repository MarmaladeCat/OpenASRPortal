"""Offline Boson wire protocol and public Portal business checks."""

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests as Portal
from websockets.exceptions import ConnectionClosedOK
from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import BOSON_MODEL, validate_config
from openasrportal.providers.boson_asr import BosonProvider
from openasrportal.providers.legacy import test_connection as probe_connection
from openasrportal.storage.store import Store

VOICE = b"\x00\x10" * 3200
ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_official_endpoint_models_language_and_secret_retention(self):
        config = validate_config(BOSON_MODEL, {"apiKey": "fictional-boson-key"})
        for changes in (
            {"endpoint": "wss://example.org/v1/realtime"}, {"model": "gpt-realtime"},
            {"language": "zh-CN"}, {"language": []}, {"silenceMs": True}, {"silenceMs": 100},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config(BOSON_MODEL, changes, config)
        self.assertEqual(validate_config(BOSON_MODEL, {"language": "zh"}, config)["apiKey"],
                         config["apiKey"])


class BosonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []
        self.audio = []
        self.commits = 0
        self.commit_seen = asyncio.Event()
        self.reply_gate = asyncio.Event()
        self.reply_gate.set()
        self.closed = asyncio.Event()
        self.mode = "normal"

        async def upstream(socket):
            try:
                self.assertEqual(socket.request_headers["Authorization"], "Bearer fictional-key")
                initial = json.loads(await socket.recv())
                self.messages.append(initial)
                self.assertEqual(initial["type"], "session.update")
                self.assertIsNone(initial["session"]["audio"]["input"]["turn_detection"])
                self.assertEqual(initial["session"]["audio"]["input"]["format"]["rate"], 16000)
                await socket.send('{"type":"session.created"}')
                async for raw in socket:
                    event = json.loads(raw)
                    self.messages.append(event)
                    if event["type"] == "input_audio_buffer.append":
                        self.audio.append(base64.b64decode(event["audio"]))
                    elif event["type"] == "input_audio_buffer.commit":
                        self.commits += 1
                        self.commit_seen.set()
                        identity = f"turn-{self.commits}"
                        await socket.send(json.dumps({
                            "type": "input_audio_buffer.committed", "item_id": identity,
                        }))
                        if self.mode == "disconnect":
                            await socket.close()
                            return
                        await self.reply_gate.wait()
                        if self.mode == "error":
                            await socket.send(json.dumps({"type": "error", "error": {
                                "message": "fictional-key private audio"}}))
                            continue
                        await socket.send(json.dumps({
                            "type": "response.output_text.done", "text": "Not a transcript",
                        }))
                        await socket.send('{"type":"conversation.item.done"}')
                        final = json.dumps({
                            "type": "conversation.item.input_audio_transcription.completed",
                            "item_id": "wrong" if self.mode == "mismatch" else identity,
                            "transcript": "" if self.mode == "empty" else f"分段{self.commits}。",
                            "usage": {"type": "duration", "seconds": 1},
                        })
                        await socket.send(final)
                        await socket.send(final)  # Duplicate completion must be idempotent.
            except ConnectionClosedOK:
                pass  # Expected when cancelling a pending transcription.
            finally:
                self.closed.set()

        self.server = await serve(upstream, "127.0.0.1", 0)
        self.config = validate_config(BOSON_MODEL, {"apiKey": "fictional-key"})
        self.config["endpoint"] = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        self.provider = BosonProvider(self.config)
        await self.provider.open()

    async def asyncTearDown(self):
        self.reply_gate.set()
        await self.provider.close()
        self.server.close()
        await self.server.wait_closed()

    async def result(self):
        return await asyncio.wait_for(self.provider.receive(), 2)

    async def test_streams_before_commit_and_preserves_two_finals_in_order(self):
        await self.provider.send_audio(VOICE)
        await self.provider.send_audio(bytes(25600))
        first, last = await self.result()
        self.assertFalse(last)
        self.assertEqual(first[0]["nbest"][0]["sentence"], "分段1。")
        await self.provider.send_audio(VOICE + b"\x00\x10", last=True)
        second, last = await self.result()
        self.assertTrue(last)
        self.assertEqual(second[0]["nbest"][0]["sentence"], "分段2。")
        self.assertEqual(b"".join(self.audio), VOICE + bytes(25600) + VOICE + b"\x00\x10")
        self.assertEqual(self.commits, 2)
        self.assertFalse(any(m["type"] == "response.create" for m in self.messages))

    async def test_backpressure_does_not_supersede_pending_transcription(self):
        self.reply_gate.clear()
        await self.provider.send_audio(VOICE + bytes(25600))
        await asyncio.wait_for(self.commit_seen.wait(), 2)
        await asyncio.wait_for(self.provider.send_audio(VOICE, last=True), .1)
        self.assertEqual(self.commits, 1)
        self.reply_gate.set()
        first, _ = await self.result()
        second, done = await self.result()
        self.assertEqual([first[0]["nbest"][0]["sentence"], second[0]["nbest"][0]["sentence"]],
                         ["分段1。", "分段2。"])
        self.assertTrue(done)

    async def test_empty_recording_and_silence_do_not_hallucinate(self):
        await self.provider.send_audio(bytes(64000), last=True)
        self.assertEqual(await self.result(), ([], True))
        self.assertEqual(self.commits, 0)
        self.assertEqual(self.audio, [])

    async def test_latency_diagnostics_do_not_log_credentials_audio_or_transcripts(self):
        with self.assertLogs("openasrportal.providers.boson_asr", level="INFO") as logs:
            await self.provider.send_audio(VOICE, last=True)
            await self.result()
        output = "\n".join(logs.output)
        self.assertIn("commit_ack_ms=", output)
        self.assertIn("final_after_commit_ms=", output)
        self.assertIn("audio_end_ms=200", output)
        for secret in ("fictional-key", "分段1。", base64.b64encode(VOICE).decode()):
            self.assertNotIn(secret, output)

    async def test_empty_transcript_is_a_successful_empty_segment(self):
        self.mode = "empty"
        await self.provider.send_audio(VOICE, last=True)
        self.assertEqual(await self.result(), ([], True))

    async def test_forced_segment_boundary_preserves_continuous_audio(self):
        with patch("openasrportal.providers.boson_asr.MAX_SEGMENT_BYTES", 6400):
            await self.provider.send_audio(VOICE)
            first, _ = await self.result()
            await self.provider.send_audio(VOICE, last=True)
            second, done = await self.result()
        self.assertEqual(len(first) + len(second), 2)
        self.assertTrue(done)
        self.assertEqual(b"".join(self.audio), VOICE * 2)

    async def test_error_redaction_and_mismatched_turn_rejection(self):
        self.mode = "error"
        await self.provider.send_audio(VOICE, last=True)
        with self.assertRaises(ProviderError) as raised:
            await self.result()
        self.assertNotIn("fictional-key", str(raised.exception))
        self.assertNotIn("private audio", str(raised.exception))

    async def test_mismatched_turn_is_not_finalized(self):
        self.mode = "mismatch"
        await self.provider.send_audio(VOICE, last=True)
        with self.assertRaises(ProviderError):
            await self.result()

    async def test_disconnect_before_transcription_is_not_success(self):
        self.mode = "disconnect"
        await self.provider.send_audio(VOICE, last=True)
        with self.assertRaises(Exception):
            await self.result()

    async def test_close_releases_reader_and_upstream(self):
        await self.provider.send_audio(VOICE)
        await self.provider.close()
        await asyncio.wait_for(self.closed.wait(), 2)
        self.assertTrue(self.provider.worker.done())
        self.assertEqual(self.commits, 0)

    async def test_pending_transcription_can_be_cancelled_and_backlog_is_bounded(self):
        self.reply_gate.clear()
        await self.provider.send_audio(VOICE + bytes(25600))
        await asyncio.wait_for(self.commit_seen.wait(), 2)
        for _ in range(60):
            await self.provider.send_audio(VOICE)
        with self.assertRaises(ProviderError):
            await self.provider.send_audio(VOICE * 20)
        await asyncio.wait_for(self.provider.close(), 2)
        self.assertTrue(self.provider.uploader.done())
        self.assertTrue(self.provider.worker.done())

    async def test_probe_exercises_transcription(self):
        result = await probe_connection(BosonProvider(self.config))
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.commits, 1)

    async def test_public_portal_finalization_cancel_and_duration_quota(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            store = Store(directory)
            store.save("boson", "Boson", BOSON_MODEL, {"apiKey": "fictional-key"})
            public = store.list()[0]
            self.assertFalse(public["capabilities"]["partialResults"])
            self.assertFalse(public["capabilities"]["tokenUsage"])
            self.assertFalse(public["capabilities"]["hotwords"]["supported"])
            self.assertNotIn("fictional-key", json.dumps(public))
            store.usage.update_quota("profile", "boson", {"remainingSeconds": .2})
            providers = []

            def factory(profile):
                provider = BosonProvider(self.config)
                providers.append(provider)
                return provider

            portal = Portal(store, "client-key", "admin-key", factory=factory)
            async with TestServer(portal.app()) as server, ClientSession(
                headers={"Authorization": "Bearer client-key"}
            ) as client:
                async def start():
                    async with client.post(server.make_url("/v1/sessions"), json={}) as response:
                        self.assertEqual(response.status, 201)
                        session = await response.json()
                    socket = await client.ws_connect(server.make_url(
                        session["streamPath"] + "?ticket=" + session["ticket"]))
                    self.assertEqual((await socket.receive_json())["type"], "session.ready")
                    return socket

                socket = await start()
                await socket.send_bytes(VOICE * 2)
                final = await socket.receive_json(timeout=2)
                done = await socket.receive_json(timeout=2)
                self.assertEqual(final["type"], "transcript.final")
                self.assertEqual((done["type"], done["finalCount"]), ("session.finished", 1))
                self.assertEqual(done["reason"], "quota_exhausted")
                await socket.close()
                quota = store.usage.quota("profile", "boson")
                self.assertEqual(quota["usedSeconds"], .2)
                self.assertIsNone(quota["tokens"])
                store.usage.update_quota("profile", "boson", {"remainingSeconds": 10})
                socket = await start()
                self.commit_seen.clear()
                self.reply_gate.clear()
                await socket.send_bytes(VOICE + bytes(25600))
                await asyncio.wait_for(self.commit_seen.wait(), 2)
                await socket.send_bytes(VOICE)
                await socket.send_json({"type": "session.cancel"})
                self.assertEqual((await socket.receive_json(timeout=2))["type"], "session.cancelled")
                await socket.close()
                self.reply_gate.set()
                used = store.usage.quota("profile", "boson")["usedSeconds"]
                async with client.post(
                    server.make_url("/v1/admin/profiles/boson/test"),
                    headers={"Authorization": "Bearer " + portal.test_admin_token},
                ) as response:
                    self.assertTrue((await response.json())["ok"])
                self.assertAlmostEqual(store.usage.quota("profile", "boson")["usedSeconds"],
                                       used + .2)
            self.assertTrue(all(provider.closed for provider in providers))
