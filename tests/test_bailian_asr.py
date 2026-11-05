"""远程百炼 HTTP 请求、VAD、预览/定稿调度与资源清理；完全离线测试。"""

import asyncio
import base64
import io
import json
import struct
import unittest
import wave

try:
    import httpx
except ImportError:
    raise unittest.SkipTest("百炼测试需要 httpx==0.28.1")

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import (
    BAILIAN_ASR_MODEL,
    BAILIAN_MODEL,
    public_config,
    validate_config,
)
from openasrportal.providers.bailian_asr import MAX_SEGMENT_BYTES, BailianProvider, parse_result


def voice(milliseconds):
    return struct.pack("<h", 1500) * (16 * milliseconds)


def config(**patches):
    return validate_config(BAILIAN_MODEL, {"apiKey": "bailian-unit-secret", **patches})


class ConfigAndResultTests(unittest.TestCase):
    def test_provider_specific_validation_and_redaction(self):
        for host in (
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "workspace-123.cn-beijing.maas.aliyuncs.com",
            "ws-test.ap-southeast-1.maas.aliyuncs.com",
        ):
            endpoint = "https://" + host + "/api/v1/services/aigc/multimodal-generation/generation"
            stored = config(endpoint=endpoint)
            view = public_config(stored, BAILIAN_MODEL)
            self.assertEqual(view["model"], BAILIAN_ASR_MODEL)
            self.assertNotIn("resourceId", view)
            self.assertNotIn("bailian-unit-secret", json.dumps(view))
        for patch_value in (
            {"endpoint": "https://example.com"},
            {"endpoint": "https://dashscope.aliyuncs.com.evil.test"},
            {"endpoint": "http://dashscope.aliyuncs.com"},
            {"model": "qwen3-asr-flash"},
            {"previewIntervalMs": True},
            {"silenceMs": 0},
            {"language": "unknown"},
            {"keepDialect": "yes"},
        ):
            with self.subTest(patch=patch_value), self.assertRaises(ValueError):
                config(**patch_value)

    def test_cumulative_text_and_documented_nested_response(self):
        self.assertEqual(
            parse_result(
                {"output": {"text": "第一句。第二句。", "sentence": {"text": "第二句。"}}}
            ),
            "第一句。第二句。",
        )
        self.assertEqual(
            parse_result({"output": {"output": {"sentence": {"text": "你好。"}}}}), "你好。"
        )
        self.assertEqual(
            parse_result({"output": {"sentences": [{"text": "甲。"}, {"text": "乙。"}]}}),
            "甲。乙。",
        )
        self.assertEqual(parse_result({"output": {"text": ""}}), "")
        for payload in ({"output": {}}, {"code": "InvalidApiKey"}, []):
            with self.assertRaises(ProviderError):
                parse_result(payload)

    def test_workspace_base_urls_normalize_to_the_dashscope_request_path(self):
        origin = "https://ws-th85oh8r45aiki7v.cn-beijing.maas.aliyuncs.com"
        expected = origin + "/api/v1/services/aigc/multimodal-generation/generation"
        for endpoint in (origin, origin + "/", origin + "/api/v1", origin + "/api/v1/", expected):
            self.assertEqual(config(endpoint=endpoint)["endpoint"], expected)
        for suffix in ("/compatible-mode/v1", "/api/v1?key=x", "/api/v1#fragment"):
            with self.assertRaises(ValueError):
                config(endpoint=origin + suffix)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_uses_exact_model_and_pcm_wav_without_redirects(self):
        seen = []

        def handler(request):
            seen.append(request)
            body = json.loads(request.content)
            self.assertEqual(body["model"], BAILIAN_ASR_MODEL)
            self.assertEqual(request.headers["Authorization"], "Bearer bailian-unit-secret")
            self.assertEqual(request.headers["X-DashScope-SSE"], "disable")
            self.assertEqual(body["parameters"]["language_hints"], ["zh"])
            self.assertTrue(body["parameters"]["keep_dialect"])
            uri = body["input"]["messages"][0]["content"][0]["input_audio"]["data"]
            with wave.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])), "rb") as wav:
                self.assertEqual(
                    (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()), (1, 16000, 2)
                )
                self.assertEqual(wav.readframes(wav.getnframes()), voice(1000))
            return httpx.Response(
                200, json={"output": {"output": {"sentence": {"text": "嗯，这个这个不改。"}}}}
            )

        provider = BailianProvider(config(language="zh", keepDialect=True))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider.client = client
            self.assertEqual(await provider._transcribe(voice(1000)), "嗯，这个这个不改。")
        self.assertEqual(len(seen), 1)

    async def test_errors_and_malformed_results_are_not_success(self):
        for response in (
            httpx.Response(401, json={"code": "InvalidApiKey", "message": "bailian-unit-secret"}),
            httpx.Response(307, headers={"Location": "https://example.com"}),
            httpx.Response(200, text="bad json"),
            httpx.Response(200, json={"output": {}}),
        ):
            provider = BailianProvider(config())
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: response), follow_redirects=False
            ) as client:
                provider.client = client
                with self.assertRaises(ProviderError) as error:
                    await provider._transcribe(voice(1000))
                self.assertNotIn("bailian-unit-secret", str(error.exception))

    async def test_official_no_words_response_is_empty_but_other_400_is_error(self):
        provider = BailianProvider(config())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    400, json={"code": "CLIENT_ERROR", "message": "ASR_RESPONSE_HAVE_NO_WORDS"}
                )
            )
        ) as client:
            provider.client = client
            self.assertEqual(await provider._transcribe(bytes(32000)), "")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    400, json={"code": "CLIENT_ERROR", "message": "invalid audio"}
                )
            )
        ) as client:
            provider.client = client
            with self.assertRaises(ProviderError):
                await provider._transcribe(bytes(32000))

    async def test_stale_preview_is_discarded_and_final_order_preserved(self):
        provider = BailianProvider(config(previewIntervalMs=1500, silenceMs=600))
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def transcribe(pcm, *, final=True):
            calls.append(pcm)
            if len(calls) == 1:
                started.set()
                await release.wait()
                return "过期预览"
            return "第一段。" if len(calls) == 2 else "第二段。"

        provider._transcribe = transcribe
        await provider.open()
        try:
            await provider.send_audio(voice(1600))
            await asyncio.wait_for(started.wait(), 1)
            await provider.send_audio(bytes(19200))
            await provider.send_audio(voice(900), last=True)
            release.set()
            events = []
            while True:
                batch, last = await asyncio.wait_for(provider.receive(), 1)
                events.extend(batch)
                if last:
                    break
            self.assertEqual([e["type"] for e in events], ["final_result", "final_result"])
            self.assertEqual([e["nbest"][0]["sentence"] for e in events], ["第一段。", "第二段。"])
            self.assertLess(
                events[0]["nbest"][0]["word_pieces"][0]["end"],
                events[1]["nbest"][0]["word_pieces"][0]["start"],
            )
        finally:
            await provider.close()

    async def test_preview_then_corrected_final_and_silence_filter(self):
        provider = BailianProvider(config(previewIntervalMs=1500))
        calls = []

        async def transcribe(pcm, *, final=True):
            calls.append(pcm)
            return "错词" if len(calls) == 1 else "正确文本。"

        provider._transcribe = transcribe
        await provider.open()
        try:
            await provider.send_audio(bytes(32000))
            self.assertEqual(calls, [])
            await provider.send_audio(voice(1600))
            events, last = await asyncio.wait_for(provider.receive(), 1)
            self.assertFalse(last)
            self.assertEqual(events[0]["type"], "partial_result")
            await provider.send_audio(voice(400), last=True)
            events, last = await asyncio.wait_for(provider.receive(), 1)
            self.assertEqual(events[0]["nbest"][0]["sentence"], "正确文本。")
            self.assertEqual(events[0]["type"], "final_result")
            self.assertEqual(await provider.receive(), ([], True))
            self.assertEqual(len(calls), 2)
        finally:
            await provider.close()

    async def test_silence_only_session_and_probe_are_distinct(self):
        provider = BailianProvider(config())
        called = []

        async def transcribe(pcm, *, final=True):
            called.append(len(pcm))
            return ""

        provider._transcribe = transcribe
        await provider.open()
        try:
            await provider.probe()
            self.assertEqual(called, [32000])
            await provider.send_audio(bytes(64000), last=True)
            self.assertEqual(await asyncio.wait_for(provider.receive(), 1), ([], True))
            self.assertEqual(called, [32000])
        finally:
            await provider.close()

    async def test_close_cancels_inflight_request_and_limits_buffering(self):
        provider = BailianProvider(config(previewIntervalMs=1500, silenceMs=600))
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def transcribe(pcm, *, final=True):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        provider._transcribe = transcribe
        await provider.open()
        try:
            await provider.send_audio(voice(1600))
            await asyncio.wait_for(started.wait(), 1)
            with self.assertRaisesRegex(ProviderError, "积压"):
                for _ in range(4):
                    await provider.send_audio(voice(1000) + bytes(19200))
            self.assertLessEqual(len(provider.buffer), MAX_SEGMENT_BYTES)
        finally:
            await provider.close()
        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
