"""Complete-file wire and admission checks; fixtures are not real-model acceptance."""

import asyncio
import base64
import io
import json
import unittest
import wave

from aiohttp import web
from aiohttp.test_utils import TestServer
from test_usage import UsageApiFixture

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import LOCAL_FILE_PATH, validate_config
from openasrportal.providers.file_audio import DataUriBody, Recording, RecordingBudget
from openasrportal.providers.localasr_file import LocalASRFileProvider
from openasrportal.providers.openai_file import OpenAIFileProvider


class FileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests, self.received = [], asyncio.Event()
        self.release = asyncio.Event()
        self.mode = "local"

        async def recognize(request):
            self.assertEqual(request.headers["Authorization"], "Bearer fictional")
            self.assertNotIn("Transfer-Encoding", request.headers)
            if self.mode == "local":
                body = await request.json()
                data = body["input"]["messages"][0]["content"][0]["input_audio"]["data"]
                wav = base64.b64decode(data.split(",", 1)[1], validate=True)
                self.assertEqual(body["parameters"], {"format": "wav", "sample_rate": "16000"})
            else:
                form = await request.post()
                self.assertEqual(form["model"], "gpt-transcribe")
                wav = form["file"].file.read()
            with wave.open(io.BytesIO(wav)) as audio:
                self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
                self.requests.append(audio.readframes(audio.getnframes()))
            self.received.set()
            await self.release.wait()
            if self.mode == "local":
                return web.json_response({"request_id": "request", "output": {"text": "完整定稿。"}})
            if self.mode == "json":
                return web.json_response({"text": "全文。", "usage": {"type": "duration", "seconds": .2}})
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            events = [{"type": "transcript.text.delta", "delta": "错误候选"}]
            if self.mode != "truncated":
                events.append({"type": "transcript.text.done", "text": "正确全文。",
                               "usage": {"type": "tokens", "total_tokens": 4, "input_tokens": 3, "output_tokens": 1}})
            data = ": heartbeat\r\n\r\n" + "".join("data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n" for event in events)
            for byte in data.encode():
                await response.write(bytes([byte]))
            return response

        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.router.add_post("/recognize", recognize)
        self.server = TestServer(app)
        await self.server.start_server()
        self.providers = []

    async def asyncTearDown(self):
        self.release.set()
        for provider in self.providers:
            await provider.close()
        await self.server.close()

    async def provider(self, mode="local"):
        self.mode = mode
        config = validate_config("openlocalasr_file" if mode == "local" else "openai_file", {"apiKey": "fictional"})
        config["endpoint"] = str(self.server.make_url("/recognize"))
        if mode != "local":
            config["responseMode"] = "json" if mode == "json" else "sse"
        provider = LocalASRFileProvider(config) if mode == "local" else OpenAIFileProvider(config)
        self.providers.append(provider)
        await provider.open()
        return provider

    async def test_full_pcm_once_and_upload_barrier_precedes_response(self):
        provider = await self.provider()
        pcm = bytes(range(256)) * 31 + b"\x01\x00"
        for offset in range(0, len(pcm), 126):
            await provider.write_audio(pcm[offset:offset + 126])
        self.assertFalse(self.requests)
        receiver = asyncio.create_task(provider.receive())
        await asyncio.wait_for(provider.finish_input(), 1)
        await asyncio.wait_for(self.received.wait(), 1)
        self.assertFalse(receiver.done())
        self.assertEqual(self.requests, [pcm])
        self.assertEqual(provider.recording.budget.reserved, 0)
        self.release.set()
        events, last = await asyncio.wait_for(receiver, 1)
        self.assertTrue(last)
        self.assertEqual(events[0].text, "完整定稿。")
        with self.assertRaises(ProviderError):
            await provider.finish_input()

    async def test_openai_json_sse_replacement_and_truncated_stream(self):
        for mode in ("json", "sse", "truncated"):
            with self.subTest(mode=mode):
                provider = await self.provider(mode)
                reports = []
                provider.usage_callback = lambda report, **_: reports.append(report)
                await provider.write_audio(bytes(6400))
                self.release.set()
                await provider.finish_input()
                if mode == "json":
                    events, last = await provider.receive()
                    self.assertTrue(last)
                    self.assertEqual(events[0].text, "全文。")
                    self.assertEqual(reports[0].kind, "duration")
                else:
                    # A failed request may race queued partials. Neither route can
                    # invent a final when the SSE terminal marker is absent.
                    collected = []
                    try:
                        while True:
                            events, last = await provider.receive()
                            collected.extend(events)
                            if last:
                                break
                    except ProviderError:
                        self.assertEqual(mode, "truncated")
                        self.assertFalse(any(event.stable for event in collected))
                    else:
                        self.assertEqual(mode, "sse")
                        self.assertEqual(collected[-1].text, "正确全文。")
                        self.assertTrue(collected[-1].stable)

    async def test_drain_receipt_waits_for_real_writer_and_memory_admission(self):
        budget = RecordingBudget(4)
        recording = Recording(budget, 4)
        recording.open()
        recording.append(bytes(4))
        with self.assertRaises(ProviderError):
            Recording(budget, 2).open()
        body = DataUriBody(recording, b"", b"")
        entered, release = asyncio.Event(), asyncio.Event()

        class Writer:
            async def write(self, data):
                pass

            async def drain(self):
                entered.set()
                await release.wait()

        writing = asyncio.create_task(body.write(Writer()))
        await entered.wait()
        self.assertFalse(body.submitted.is_set())
        release.set()
        await writing
        self.assertTrue(body.submitted.is_set())
        self.assertEqual(budget.reserved, 0)


class FileAdmissionTests(UsageApiFixture, unittest.IsolatedAsyncioTestCase):
    async def test_client_tcp_loss_releases_file_cache_and_allows_same_key_again(self):
        self.store.save("file", "File", "openai_file", {"apiKey": "fictional"})
        budget = RecordingBudget(9600000)
        providers = []

        def factory(profile):
            provider = OpenAIFileProvider({**profile["configuration"], "_recordingBudget": budget,
                                          "endpoint": "http://127.0.0.1:1/unused"})
            providers.append(provider)
            return provider

        self.portal.factory = factory
        for _ in range(2):
            async with self.client.post(self.url("/v1/sessions"), json={"profileId": "file"}) as response:
                self.assertEqual(response.status, 201)
                descriptor = await response.json()
            socket = await self.client.ws_connect(self.url(descriptor["streamPath"] + "?ticket=" + descriptor["ticket"]))
            self.assertEqual((await socket.receive_json())["type"], "session.ready")
            self.assertGreater(budget.reserved, 0)
            await socket.send_bytes(bytes(6400))
            socket._response.connection.transport.abort()
            await socket.close()
            deadline = asyncio.get_running_loop().time() + 2
            while budget.reserved:
                self.assertLess(asyncio.get_running_loop().time(), deadline)
                await asyncio.sleep(.005)
        self.assertEqual(self.store.usage.quota("key", self.key_id)["requests"], 0)
        self.assertTrue(all(provider.request is None for provider in providers))

    async def test_openai_zero_and_pre_end_cancel_make_no_paid_request_or_token_block(self):
        self.store.save("file", "File", "openai_file", {"apiKey": "fictional"})
        self.store.usage.update_quota("key", self.key_id, {"remainingTokens": 100})
        providers = []
        budget = RecordingBudget()

        def factory(profile):
            provider = OpenAIFileProvider({**profile["configuration"], "_recordingBudget": budget,
                                          "endpoint": "http://127.0.0.1:1/unused"})
            providers.append(provider)
            return provider

        self.portal.factory = factory
        for cancel in (False, True):
            async with self.client.post(self.url("/v1/sessions"), json={"profileId": "file"}) as response:
                descriptor = await response.json()
            socket = await self.client.ws_connect(self.url(descriptor["streamPath"] + "?ticket=" + descriptor["ticket"]))
            await socket.receive_json()
            if cancel:
                await socket.send_bytes(bytes(6400))
            await socket.send_json({"type": "session.cancel" if cancel else "audio.end"})
            event = await socket.receive_json(timeout=1)
            self.assertEqual(event["type"], "session.cancelled" if cancel else "session.finished")
            await socket.receive()
            await socket.close()
        quota = self.store.usage.quota("key", self.key_id)
        self.assertEqual(quota["requests"], 0)
        self.assertFalse(quota["tokenBlocked"])
        self.assertEqual(budget.reserved, 0)
        self.assertTrue(all(provider.request is None for provider in providers))

    async def test_file_duration_quota_still_submits_the_accepted_recording_once(self):
        requests = []

        async def recognize(request):
            form = await request.post()
            with wave.open(form["file"].file, "rb") as audio:
                requests.append(audio.readframes(audio.getnframes()))
            return web.json_response({"text": "限额定稿。", "usage": {"type": "duration", "seconds": .1}})

        app = web.Application()
        app.router.add_post("/transcribe", recognize)
        async with TestServer(app) as upstream:
            self.store.save("file", "File", "openai_file", {"apiKey": "fictional"})
            self.store.usage.update_quota("profile", "file", {"remainingSeconds": .1})
            self.portal.factory = lambda profile: OpenAIFileProvider({
                **profile["configuration"], "endpoint": str(upstream.make_url("/transcribe"))})
            async with self.client.post(self.url("/v1/sessions"), json={"profileId": "file"}) as response:
                descriptor = await response.json()
            socket = await self.client.ws_connect(self.url(descriptor["streamPath"] + "?ticket=" + descriptor["ticket"]))
            await socket.receive_json()
            await socket.send_bytes(bytes(6400))
            events = await self.terminal(socket)
            self.assertEqual(events[-1]["type"], "session.finished")
            self.assertTrue(events[-1]["truncated"])
            self.assertEqual(events[-1]["submittedAudioSamples"], 1600)
            self.assertEqual(requests, [bytes(3200)])
            self.assertEqual(self.store.usage.quota("profile", "file")["requests"], 1)
            await socket.close()

    async def test_short_profile_requires_explicit_limit_negotiation_and_snapshot(self):
        self.store.save("file", "File", "openlocalasr_file", {"apiKey": "fictional"})
        for features, status in (([], 400), (["effectiveSessionLimits"], 201)):
            async with self.client.post(self.url("/v1/sessions"), json={
                    "profileId": "file", "requiredFeatures": features}) as response:
                self.assertEqual(response.status, status)
                data = await response.json()
                if status == 201:
                    self.assertEqual(data["limits"]["maxRecordingMs"], 60000)
                    self.assertEqual(data["capabilities"]["recognition"]["preview"]["phase"], "none")
                    await self.client.delete(self.url("/v1/sessions/" + data["sessionId"]))
        async with self.client.post(self.url("/v1/sessions"), json={
                "profileId": "file", "requiredFeatures": ["effectiveSessionLimits", "realtimePreview"]}) as response:
            self.assertEqual(response.status, 400)

    async def test_zero_audio_file_finishes_locally_without_http_submission(self):
        self.store.save("file", "File", "openlocalasr_file", {
            "apiKey": "fictional", "endpoint": "http://127.0.0.1:1" + LOCAL_FILE_PATH})
        self.portal.factory = lambda profile: LocalASRFileProvider(profile["configuration"])
        async with self.client.post(self.url("/v1/sessions"), json={
                "profileId": "file", "requiredFeatures": ["effectiveSessionLimits"]}) as response:
            descriptor = await response.json()
        socket = await self.client.ws_connect(self.url(descriptor["streamPath"] + "?ticket=" + descriptor["ticket"]))
        self.assertEqual((await socket.receive_json())["type"], "session.ready")
        await socket.send_json({"type": "audio.end"})
        final = await socket.receive_json(timeout=1)
        self.assertEqual((final["type"], final["finalCount"], final["acceptedAudioSamples"]), ("session.finished", 0, 0))
        await socket.close()
