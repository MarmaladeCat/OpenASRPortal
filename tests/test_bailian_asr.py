"""Offline duplex wire tests; no simulated HTTP recognition implementation."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.exceptions import ConnectionClosedOK
from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import BAILIAN_ASR_MODEL, BAILIAN_MODEL, validate_config
from openasrportal.providers.bailian_asr import BailianProvider
from openasrportal.storage.store import Store

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_official_domains_and_reject_http_or_wrong_model(self):
        for host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                     "workspace.cn-beijing.maas.aliyuncs.com", "workspace.ap-southeast-1.maas.aliyuncs.com"):
            value = validate_config(BAILIAN_MODEL, {"apiKey": "fictional", "endpoint": "wss://" + host})
            self.assertEqual(value["endpoint"], "wss://" + host + "/api-ws/v1/inference")
        for change in ({"endpoint": "https://dashscope.aliyuncs.com"},
                       {"endpoint": "wss://dashscope.aliyuncs.com.evil.org"},
                       {"endpoint": "wss://key@dashscope.aliyuncs.com"},
                       {"model": "qwen-audio-3.1-asr-flash"}, {"silenceMs": True}):
            with self.assertRaises(ValueError):
                validate_config(BAILIAN_MODEL, {"apiKey": "fictional", **change})

    def test_stored_http_profile_migrates_without_losing_key_region_or_quota(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            store = Store(directory)
            store.save("old", "Old", BAILIAN_MODEL, {"apiKey": "fictional"})
            old = {"apiKey": "retained", "model": "qwen-audio-3.1-asr-flash",
                   "endpoint": "https://workspace.ap-southeast-1.maas.aliyuncs.com/api/v1",
                   "previewIntervalMs": 2500, "silenceMs": 1200}
            with store.connection() as db:
                db.execute("UPDATE profiles SET configuration=? WHERE id='old'", (json.dumps(old),))
            store.usage.update_quota("profile", "old", {"remainingTokens": 123})
            profile = store.get("old")
            self.assertEqual(profile["configuration"]["model"], BAILIAN_ASR_MODEL)
            self.assertEqual(profile["configuration"]["apiKey"], "retained")
            self.assertNotIn("previewIntervalMs", profile["configuration"])
            public = store.save("old", "Old", BAILIAN_MODEL, {})
            self.assertEqual(public["quota"]["remainingTokens"], 123)
            self.assertNotIn("retained", json.dumps(public))
            self.assertEqual(public["capabilities"]["latencyClass"], "streaming")


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.audio = []
        self.commands = []
        self.bad = None
        async def handle(ws):
            self.assertEqual(ws.request_headers["Authorization"], "Bearer fictional")
            command = json.loads(await ws.recv())
            self.commands.append(command)
            self.task = command["header"]["task_id"]
            async def event(kind, payload):
                await ws.send(json.dumps({"header": {"event": kind, "task_id": self.task}, "payload": payload}))
            await event("task-started", {})
            try:
                async for message in ws:
                    if isinstance(message, bytes):
                        self.audio.append(message)
                        if self.bad:
                            await ws.send(self.bad)
                        else:
                            await event("result-generated", {"output": {"sentence": {
                                "sentence_id": 0, "text": "预览", "begin_time": 0,
                                "end_time": None, "sentence_end": False}}})
                    else:
                        self.commands.append(json.loads(message))
                        sentence = {"sentence_id": 0, "text": "定稿。", "begin_time": 0,
                                    "end_time": 200, "sentence_end": True}
                        for _ in range(2):
                            await event("result-generated", {"output": {"sentence": sentence},
                                                               "usage": {"total_tokens": 5}})
                        await event("task-finished", {"usage": {"total_tokens": 7}})
            except ConnectionClosedOK:
                pass
        self.server = await serve(handle, "127.0.0.1", 0)
        config = validate_config(BAILIAN_MODEL, {"apiKey": "fictional", "language": "zh"})
        config["endpoint"] = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        config["hotwords"] = [{"text": "麒麟", "weight": 3}]
        self.provider = BailianProvider(config)
        await self.provider.open()

    async def asyncTearDown(self):
        await self.provider.close()
        self.server.close()
        await self.server.wait_closed()

    async def test_partial_before_end_single_upload_and_deduplicated_finals(self):
        pcm = bytes(6400)
        await self.provider.send_audio(pcm)
        events, done = await asyncio.wait_for(self.provider.receive(), 2)
        self.assertFalse(done)
        self.assertEqual(events[0]["type"], "partial_result")
        await self.provider.send_audio(b"", last=True)
        finals = []
        while not done:
            events, done = await self.provider.receive()
            finals.extend(events)
        self.assertEqual([e["nbest"][0]["sentence"] for e in finals], ["定稿。"])
        self.assertEqual(self.audio, [pcm])
        self.assertEqual([c["header"]["action"] for c in self.commands], ["run-task", "finish-task"])
        parameters = self.commands[0]["payload"]["parameters"]
        self.assertEqual(parameters["vocabulary"], {"麒麟": 3})
        self.assertEqual(parameters["language_hints"], ["zh"])
        self.assertEqual(self.commands[0]["payload"]["model"], BAILIAN_ASR_MODEL)

    async def test_malformed_and_upstream_errors_are_sanitized(self):
        for payload in ("[]", "null", json.dumps({"header": {"task_id": self.task,
                        "event": "task-failed", "error_message": "fictional"}})):
            with self.assertRaises(ProviderError) as error:
                self.provider.parse(payload)
            self.assertNotIn("fictional", str(error.exception))

    async def test_heartbeat_and_missing_final(self):
        def message(kind, payload):
            return json.dumps({"header": {"event": kind, "task_id": self.task}, "payload": payload})
        with patch.object(self.provider.socket, "recv", side_effect=[
            message("result-generated", {"output": {"sentence": {"heartbeat": True}}}),
            message("task-finished", {}),
        ]):
            self.assertEqual(await self.provider.receive(), ([], False))
            self.provider.ending, self.provider.pending = True, 0
            with self.assertRaises(ProviderError):
                await self.provider.receive()
