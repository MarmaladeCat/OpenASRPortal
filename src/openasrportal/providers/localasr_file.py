"""OpenLocalASR public HTTP WAV API, one request after audio.end (no SSE)."""

import json

import aiohttp

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import ProviderEvent, protocol_error
from .buffered_file import BufferedFileProvider
from .file_audio import DataUriBody
from .transport import http_options


class LocalASRFileProvider(BufferedFileProvider):
    label = "OpenLocalASR HTTP"

    def make_body(self):
        prefix = ('{"model":' + json.dumps(self.config["model"]) + ',"input":{"messages":['
                  '{"role":"user","content":[{"type":"input_audio","input_audio":'
                  '{"data":"data:audio/wav;base64,').encode()
        suffix = b'"}}]}]},"parameters":{"format":"wav","sample_rate":"16000"}}'
        return DataUriBody(self.recording, prefix, suffix)

    async def recognize(self, body):
        options = http_options(self.config)
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(
                total=None, sock_connect=10)) as client:
            async with client.post(self.config["endpoint"], data=body, allow_redirects=False,
                                   headers={"Authorization": "Bearer " + self.config["apiKey"]},
                                   **options) as response:
                if response.status != 200:
                    raise ProviderError.upstream(self.label, response.status)
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 4 * 1024 * 1024:
                        raise protocol_error()
                try:
                    data = json.loads(raw)
                    text = data["output"]["text"]
                    request_id = data["request_id"]
                    event = ProviderEvent(request_id, 0, 1, text, True, source="openlocalasr_file")
                except (ValueError, KeyError, TypeError):
                    raise protocol_error() from None
                await self.events.put(([event], True))
