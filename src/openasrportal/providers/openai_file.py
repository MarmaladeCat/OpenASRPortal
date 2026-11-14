"""One complete WAV upload, JSON or post-upload SSE transcription."""

import asyncio
import uuid

import aiohttp
from aiohttp.payload import Payload

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import MAX_TEXT, ResultEmitter, protocol_error
from . import sse
from .buffered_file import BufferedFileProvider
from .openai_common import context, parse, usage
from .transport import http_options


class MultipartWav(Payload):
    def __init__(self, recording, fields):
        boundary = uuid.uuid4().hex
        super().__init__(None, content_type="multipart/form-data; boundary=" + boundary)
        self.recording = recording
        pieces = []
        for key, value in fields.items():
            for item in value if isinstance(value, list) else [value]:
                name = key + "[]" if isinstance(value, list) else key
                pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{item}\r\n')
        pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.wav"'
                      '\r\nContent-Type: audio/wav\r\n\r\n')
        self.prefix = "".join(pieces).encode()
        self.suffix = f"\r\n--{boundary}--\r\n".encode()
        self._size = len(self.prefix) + recording.size + 44 + len(self.suffix)
        self.submitted = asyncio.Event()

    def decode(self, encoding="utf-8", errors="strict"):
        raise TypeError("An audio multipart body cannot be decoded as text")

    async def write(self, writer):
        await writer.write(self.prefix)
        for chunk in self.recording.wav():
            await writer.write(chunk)
        await writer.write(self.suffix)
        await writer.drain()
        self.submitted.set()
        self.recording.close()


class OpenAIFileProvider(BufferedFileProvider):
    label = "OpenAI"
    max_audio_bytes = 300 * 32000
    finish_timeout = 120
    token_metered = True
    scoped_usage = True

    def __init__(self, config):
        super().__init__(config)
        self.results = ResultEmitter()
        self.identity = uuid.uuid4().hex
        self.usage_callback = None

    def make_body(self):
        fields = context(self.config)
        if self.config["responseMode"] == "sse":
            fields["stream"] = "true"
        return MultipartWav(self.recording, fields)

    async def recognize(self, body):
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(
                total=None, sock_connect=10)) as client:
            async with client.post(self.config["endpoint"], data=body, allow_redirects=False,
                                   headers={"Authorization": "Bearer " + self.config["apiKey"]},
                                   **http_options(self.config)) as response:
                if response.status != 200:
                    raise ProviderError.upstream("OpenAI", response.status)
                if self.config["responseMode"] == "json":
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 4 * 1024 * 1024:
                            raise protocol_error()
                    await self.done(parse(raw))
                    return
                if response.content_type != "text/event-stream":
                    raise protocol_error()
                text, complete = "", False
                async for kind, raw in sse.events(response.content.iter_chunked(65536)):
                    event = parse(raw)
                    event_type = event.get("type")
                    if kind and kind != event_type:
                        raise protocol_error()
                    if event_type == "transcript.text.delta":
                        if complete or not isinstance(event.get("delta"), str):
                            raise protocol_error()
                        text += event["delta"]
                        if len(text) > MAX_TEXT:
                            raise protocol_error()
                        await self.events.put((self.results.replace(self.identity, 0, text, source="openai_file"), False))
                    elif event_type == "transcript.text.done":
                        if complete:
                            raise protocol_error()
                        complete = True
                        await self.done(event)
                        return  # done is the documented completion boundary, not TCP EOF.
                    else:
                        raise protocol_error()
                raise protocol_error()

    async def done(self, event):
        if self.usage_callback:
            self.usage_callback(usage(event, self.identity), final=True)
        events = self.results.replace(self.identity, 0, event.get("text"), stable=True, source="openai_file")
        await self.events.put((events, True))
