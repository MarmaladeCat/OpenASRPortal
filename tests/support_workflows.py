"""Synthetic supplier HTTP/WS peers for the separate-process Input contract probe."""

import asyncio
import base64
import io
import json
import wave

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from openasrportal.domain.transcript import ProviderEvent
from openasrportal.providers.registry import PROVIDERS

TEXT = "最终文本。"
PCM = b"\x01\x00" * 3200
WORKFLOWS = {
    "ordered": ("bailian_qwen_asr", {}),
    "local-file": ("openlocalasr_file", {}),
    "file-json": ("openai_file", {"responseMode": "json"}),
    "file-sse": ("openai_file", {"responseMode": "sse"}),
    "realtime": ("openai_realtime", {}),
    "commit": ("openai_realtime", {"model": "gpt-transcribe"}),
}


class OrderedProvider:
    finish_timeout = 2
    text_processing = "native"

    def __init__(self):
        self.events = asyncio.Queue()
        self.pcm = bytearray()

    async def open(self):
        pass

    async def write_audio(self, pcm):
        self.pcm.extend(pcm)
        if len(self.pcm) == len(pcm):
            await self.events.put(([ProviderEvent("A", 0, 1, "临时"),
                                    ProviderEvent("B", 1, 1, "文本。", True)], False))

    async def finish_input(self):
        assert self.pcm == PCM
        await self.events.put(([ProviderEvent("A", 0, 2, "最终", True)], True))

    async def receive(self):
        return await self.events.get()

    async def close(self):
        pass


class WorkflowPeers:
    def __init__(self):
        self.requests = []
        self.commits = []
        app = web.Application()
        app.router.add_post("/{kind}", self.file)
        app.router.add_get("/{kind}", self.realtime)
        self.server = TestServer(app)

    async def file(self, request):
        kind = request.match_info["kind"]
        if kind == "local-file":
            data = await request.json()
            uri = data["input"]["messages"][0]["content"][0]["input_audio"]["data"]
            raw = io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))
        else:
            form = await request.post()
            assert form["model"] == "gpt-transcribe"
            raw = form["file"].file
        with wave.open(raw, "rb") as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
            assert audio.readframes(audio.getnframes()) == PCM
        self.requests.append(kind)
        if kind == "local-file":
            return web.json_response({"request_id": "local-file", "output": {"text": TEXT}})
        usage = {"type": "tokens", "total_tokens": 4, "input_tokens": 3, "output_tokens": 1}
        if kind == "file-json":
            return web.json_response({"text": TEXT, "usage": usage})
        assert form["stream"] == "true"
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for event in ({"type": "transcript.text.delta", "delta": "旧预览"},
                      {"type": "transcript.text.done", "text": TEXT, "usage": usage}):
            payload = ("data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n").encode()
            for offset in range(0, len(payload), 5):
                await response.write(payload[offset:offset + 5])
        return response

    async def realtime(self, request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        update = await socket.receive_json()
        assert update["type"] == "session.update"
        session = update["session"]
        assert session["audio"]["input"]["turn_detection"] is None
        await socket.send_json({"type": "session.updated", "session": session})
        pcm = bytearray()
        preview = False
        async for message in socket:
            assert message.type == WSMsgType.TEXT
            event = json.loads(message.data)
            if event["type"] == "input_audio_buffer.append":
                pcm.extend(base64.b64decode(event["audio"]))
                if not preview and request.match_info["kind"] == "realtime":
                    preview = True
                    await socket.send_json({"type": "conversation.item.input_audio_transcription.delta",
                                            "item_id": "turn", "content_index": 0, "delta": "旧预览"})
            else:
                assert event["type"] == "input_audio_buffer.commit"
                assert len(pcm) == 4800 * 2
                self.commits.append(request.match_info["kind"])
                await socket.send_json({"type": "input_audio_buffer.committed", "item_id": "turn",
                                        "previous_item_id": None})
                await socket.send_json({"type": "conversation.item.input_audio_transcription.completed",
                                        "item_id": "turn", "content_index": 0, "transcript": TEXT,
                                        "usage": {"type": "duration", "seconds": .2}})
        return socket

    def configure(self, store):
        for name, (provider, options) in WORKFLOWS.items():
            store.save("workflow-" + name, name, provider, {"apiKey": "fictional", **options})

    def provider(self, profile):
        kind = profile["id"].removeprefix("workflow-")
        if kind == "ordered":
            return OrderedProvider()
        endpoint = str(self.server.make_url("/" + kind))
        if kind in {"realtime", "commit"}:
            endpoint = "ws" + endpoint[4:]
        return PROVIDERS[profile["provider"]]({**profile["configuration"], "endpoint": endpoint})

    def verify(self):
        assert sorted(self.requests) == ["file-json", "file-sse", "local-file"], self.requests
        assert sorted(self.commits) == ["commit", "realtime"], self.commits
