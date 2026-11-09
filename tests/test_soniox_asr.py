"""Soniox wire, stabilization, endpoint and public v1 business regressions."""

import asyncio
import json
import unittest

from test_usage import UsageApiFixture
from websockets.exceptions import ConnectionClosedOK
from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import SONIOX_MODEL, validate_config
from openasrportal.domain.hotwords import DEFAULTS, select_terms
from openasrportal.providers.soniox_asr import SonioxProvider


def token(text, final, start=0, end=100):
    return {"text": text, "is_final": final, "start_ms": start, "end_ms": end}


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.provider = SonioxProvider(validate_config(SONIOX_MODEL, {"apiKey": "fictional"}))

    def feed(self, tokens, **extra):
        return self.provider.parse(json.dumps({"tokens": tokens, **extra}))[0]

    def texts(self, events):
        return [(e["type"], e["nbest"][0]["sentence"]) for e in events]

    def test_config_secret_retention_and_validation(self):
        self.assertEqual(self.provider.parameters()['language_hints'], ['en', 'zh'])
        config = validate_config(SONIOX_MODEL, {"language": "zh"}, self.provider.config)
        self.assertEqual(config["apiKey"], "fictional")
        for change in ({"endpoint": "wss://example.org"}, {"model": "stt-async-v4"},
                       {"language": "ZH"}, {"endpointDelayMs": True}, {"endpointDelayMs": 3001}):
            with self.assertRaises(ValueError):
                validate_config(SONIOX_MODEL, change, config)

    def test_empty_endpoint_and_unbounded_segment(self):
        self.assertEqual(self.feed([token("<end>", True)]), [])
        with self.assertRaises(ProviderError):
            self.feed([token("x" * 65537, True)])

    def test_stable_tokens_accumulate_and_provisional_suffix_is_replaced(self):
        self.assertEqual(self.texts(self.feed([token("Hello", False)])), [("partial_result", "Hello")])
        self.assertEqual(self.texts(self.feed([token("Hello", True), token(" word", False)])),
                         [("partial_result", "Hello word")])
        self.assertEqual(self.texts(self.feed([token(" world", False)])), [("partial_result", "Hello world")])
        self.assertEqual(self.texts(self.feed([token(" world", True), token("<end>", True),
                                              token("Next", False, 200, 300)])),
                         [("final_result", "Hello world"), ("partial_result", "Next")])
        self.provider.ending = True
        self.assertEqual(self.texts(self.feed([token("Next", True, 200, 300)], finished=True)),
                         [("final_result", "Next")])

    def test_malformed_error_and_unfinished_suffix_are_not_success(self):
        for message in ("null", "[]", '{"error_code":401,"error_message":"fictional"}',
                        '{"tokens":[{"text":"bad","is_final":"false"}]}',
                        '{"tokens":[{"text":"<end>","is_final":false}]}',
                        '{"finished":true}'):
            with self.assertRaises(ProviderError) as error:
                self.provider.parse(message)
            self.assertNotIn("fictional", str(error.exception))
        self.provider.ending = True
        with self.assertRaises(ProviderError):
            self.feed([token("unfinished", False)], finished=True)
        self.feed([token("unfinished", False)])
        with self.assertRaises(ProviderError):
            self.feed([], finished=True)

    def test_context_budget_and_no_weight_or_api_key_in_start(self):
        terms = [{"text": "长词" * 20, "weight": 5}] * 2000
        selection = select_terms(SONIOX_MODEL, terms, {**DEFAULTS, "enabled": True, "maxWords": 2000})
        self.assertLess(selection["appliedCount"], 100)
        self.assertLessEqual(selection["budgetUsed"], 7000)
        self.provider.config["hotwords"] = selection["terms"]
        self.assertEqual(self.provider.parameters()["context"]["terms"][0], terms[0]["text"])
        self.assertNotIn("fictional", json.dumps(self.provider.parameters()))


class BusinessTests(UsageApiFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.audio = []
        self.controls = []
        self.closed = asyncio.Event()
        self.stall = False
        self.fail = False
        async def handle(ws):
            self.assertEqual(ws.request_headers["Authorization"], "Bearer fictional")
            self.start = json.loads(await ws.recv())
            try:
                async for message in ws:
                    if isinstance(message, bytes):
                        self.audio.append(message)
                        await ws.send(json.dumps({"tokens": [token("正在", False)]}))
                    elif message == "":
                        self.controls.append(message)
                        if self.fail:
                            await ws.send('{"error_code":400,"error_message":"fictional"}')
                        elif not self.stall:
                            await ws.send(json.dumps({"tokens": [token("正在识别。", True), token("<end>", True)]}))
                            await ws.send('{"tokens":[],"finished":true}')
                    else:
                        self.controls.append(json.loads(message))
            except ConnectionClosedOK:
                pass
            finally:
                self.closed.set()
        self.upstream = await serve(handle, "127.0.0.1", 0)
        self.store.save("soniox", "Soniox", SONIOX_MODEL, {"apiKey": "fictional", "language": "zh"})
        self.store.set_default("soniox")
        def factory(profile):
            provider = SonioxProvider({**profile["configuration"], "endpoint":
                f"ws://127.0.0.1:{self.upstream.sockets[0].getsockname()[1]}"})
            provider.keepalive_interval = 0.05
            provider.finish_timeout = 0.1 if self.stall else 2
            return provider
        self.portal.factory = factory

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.upstream.close()
        await self.upstream.wait_closed()

    async def test_partial_before_end_final_once_empty_text_end_and_usage(self):
        socket = await self.session()
        self.assertEqual((await socket.receive_json())["type"], "session.ready")
        await socket.send_bytes(bytes(6400))
        partial = await socket.receive_json(timeout=2)
        self.assertEqual(partial["type"], "transcript.partial")
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["finalCount"], 1)
        self.assertEqual(events[0]["text"], "正在识别。")
        self.assertEqual(events[0]["utteranceId"], partial["utteranceId"])
        self.assertEqual(self.audio, [bytes(6400)])
        self.assertEqual(self.controls[-1], "")
        self.assertEqual(self.start["model"], "stt-rt-v6")
        self.assertEqual(self.start["language_hints"], ["zh"])
        self.assertEqual(self.store.usage.quota("profile", "soniox")["usedSeconds"], 0.2)
        await socket.close()

    async def test_probe_requires_finished_and_meters_upstream_only(self):
        async with self.client.post(self.url("/v1/admin/profiles/soniox/test"), headers=self.admin) as response:
            self.assertTrue((await response.json())["ok"])
        self.assertEqual(self.store.usage.quota("profile", "soniox")["usedSeconds"], 0.2)
        self.assertEqual(self.store.usage.quota("key", self.key_id)["usedSeconds"], 0)

    async def test_keepalive_and_cancel_close_without_finalizing(self):
        socket = await self.session()
        await socket.receive_json()
        # Await a protocol event, with a fixed deadline; this is a test, not tool polling.
        async def kept_alive():
            while not self.controls:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(kept_alive(), 2)
        self.assertEqual(self.controls[0], {"type": "keepalive"})
        await socket.send_json({"type": "session.cancel"})
        self.assertEqual((await socket.receive_json())["type"], "session.cancelled")
        await asyncio.wait_for(self.closed.wait(), 2)
        self.assertNotIn("", self.controls)
        await socket.close()

    async def test_final_timeout_is_an_error(self):
        self.stall = True
        socket = await self.session()
        await socket.send_bytes(bytes(6400))
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["code"], "FINALIZATION_TIMEOUT")
        await socket.close()

    async def test_error_and_duration_quota(self):
        self.store.usage.update_quota("profile", "soniox", {"remainingSeconds": 0.1})
        socket = await self.session()
        await socket.send_bytes(bytes(6400))
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["reason"], "quota_exhausted")
        self.assertEqual(len(b"".join(self.audio)), 3200)
        await socket.close()
        self.store.usage.update_quota("profile", "soniox", {"remainingSeconds": 10})
        self.store.set_default("soniox")
        self.fail = True
        socket = await self.session()
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["type"], "session.error")
        self.assertNotIn("fictional", json.dumps(events))
        await socket.close()
