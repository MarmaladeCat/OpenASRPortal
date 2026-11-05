import json
import unittest

from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import validate_config
from openasrportal.providers.dashscope_asr import DashScopeProvider


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_and_final_deduplication(self):
        async def upstream(ws):
            self.assertEqual(ws.request_headers["Authorization"], "Bearer test-key")
            request = json.loads(await ws.recv())
            self.assertEqual(request["header"]["action"], "run-task")
            self.assertEqual(request["payload"]["model"], "funasr_sensevoice_small")
            task = request["header"]["task_id"]

            async def send(kind, sentence=None):
                await ws.send(
                    json.dumps(
                        {
                            "header": {"event": kind, "task_id": task},
                            "payload": {"output": {"sentence": sentence}} if sentence else {},
                        }
                    )
                )

            await send("task-started")
            self.assertEqual(await ws.recv(), bytes(6400))
            for final, text in ((False, "错字"), (True, "正确。"), (True, "正确。")):
                await send(
                    "result-generated",
                    {
                        "sentence_id": 1,
                        "begin_time": 0,
                        "end_time": 200,
                        "text": text,
                        "sentence_end": final,
                    },
                )
            self.assertEqual(json.loads(await ws.recv())["header"]["action"], "finish-task")
            await send("task-finished")

        async with serve(upstream, "127.0.0.1", 0) as server:
            provider = DashScopeProvider(
                {
                    "endpoint": "ws://127.0.0.1:%d" % server.sockets[0].getsockname()[1],
                    "model": "funasr_sensevoice_small",
                    "apiKey": "test-key",
                }
            )
            try:
                await provider.open()
                await provider.send_audio(bytes(6400))
                self.assertEqual((await provider.receive())[0][0]["type"], "partial_result")
                self.assertEqual((await provider.receive())[0][0]["nbest"][0]["sentence"], "正确。")
                self.assertEqual(await provider.receive(), ([], False))
                await provider.send_audio(b"", last=True)
                self.assertEqual(await provider.receive(), ([], True))
            finally:
                await provider.close()

    async def test_configuration_requires_explicit_key_and_valid_endpoint(self):
        for patch in (
            {},
            {"apiKey": "key", "endpoint": "http://localhost/"},
            {"apiKey": "key", "endpoint": "ws://user:secret@localhost/api-ws/v1/inference"},
            {"apiKey": "key", "model": "../weights"},
        ):
            with self.assertRaises(ValueError):
                validate_config("openlocalasr", patch)
        config = validate_config("openlocalasr", {"apiKey": "key"})
        self.assertEqual(config["endpoint"], "ws://127.0.0.1:10095/api-ws/v1/inference")

    async def test_task_mismatch_is_not_accepted(self):
        provider = DashScopeProvider({})
        with self.assertRaises(ProviderError):
            provider.parse(json.dumps({"header": {"task_id": "wrong", "event": "task-finished"}}))
