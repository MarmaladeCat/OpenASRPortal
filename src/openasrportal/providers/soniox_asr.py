"""Soniox real-time tokens: stable prefix plus a replaceable provisional suffix."""

import asyncio
import json
import time

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError, text_event
from .transport import connect


class SonioxProvider:
    label = "Soniox"
    text_processing = "native"
    finish_timeout = 30
    keepalive_interval = 10

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.ending = False
        self.send_lock = asyncio.Lock()
        self.stable = ""
        self.preview = ""
        self.start = None
        self.end = 0
        self.last_sent = time.monotonic()

    def parameters(self):
        result = {"model": self.config["model"], "audio_format": "pcm_s16le",
                  "sample_rate": 16000, "num_channels": 1,
                  "enable_endpoint_detection": True,
                  "max_endpoint_delay_ms": self.config["endpointDelayMs"]}
        if self.config["language"] != "auto":
            result["language_hints"] = list(dict.fromkeys(self.config["language"].split(',')))
        if self.config.get("hotwords"):
            result["context"] = {"terms": [term["text"] for term in self.config["hotwords"]]}
        return result

    async def open(self):
        try:
            self.socket = await connect(
                self.config["endpoint"],
                use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                extra_headers={"Authorization": "Bearer " + self.config["apiKey"]},
                open_timeout=6, close_timeout=1, max_size=4 * 1024 * 1024, max_queue=16,
            )
        except InvalidStatusCode as error:
            raise ProviderError("Soniox 连接失败（HTTP %d），请检查 API Key" % error.status_code) from None
        await self.socket.send(json.dumps(self.parameters()))
        self.last_sent = time.monotonic()

    async def send_audio(self, pcm, last=False):
        async with self.send_lock:
            if self.ending:
                raise ProviderError("Soniox 音频已经结束")
            if pcm:
                await self.socket.send(pcm)
                self.last_sent = time.monotonic()
            if last:
                self.ending = True
                await self.socket.send("")  # Protocol requires an empty TEXT frame.

    def finalize(self):
        event = text_event("final_result", self.stable, self.start or 0, self.end, "soniox")
        self.stable, self.preview, self.start = "", "", None
        return event

    def parse(self, raw):
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError()
            if message.get("error_code") or message.get("error_type"):
                raise ProviderError("Soniox 识别失败，请检查密钥、模型权限、额度与音频参数")
            tokens = message.get("tokens", [])
            if not isinstance(tokens, list):
                raise ValueError()
            events, provisional = [], ""
            for token in tokens:
                text, final = token["text"], token["is_final"]
                if not isinstance(text, str) or type(final) is not bool:
                    raise ValueError()
                if text in ("<end>", "<fin>"):
                    if not final or provisional:
                        raise ValueError()
                    if not self.stable and self.preview:
                        raise ValueError()
                    if self.stable or self.preview:
                        events.append(self.finalize())
                    continue
                if final and provisional:
                    raise ValueError()
                for field in ("start_ms", "end_ms"):
                    value = token.get(field)
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError()
                if self.start is None:
                    self.start = token.get("start_ms", self.end)
                if final:
                    self.stable += text
                    self.end = max(self.end, token.get("end_ms", self.end))
                else:
                    provisional += text
            if len(self.stable) + len(provisional) > 65536:
                raise ValueError()  # Bound an un-ended or malformed segment.
            finished = message.get("finished") is True
            if finished:
                if (not self.ending or provisional or
                        (not tokens and self.preview != self.stable)):
                    raise ValueError()
                if self.stable or self.preview:
                    events.append(self.finalize())
            elif "tokens" in message:
                preview = self.stable + provisional
                if preview != self.preview:
                    events.append(text_event("partial_result", preview, self.start or 0,
                                             self.end, "soniox"))
                    self.preview = preview
            return events, finished
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("Soniox 返回了无效的流式识别结果") from None

    async def receive(self):
        while True:
            try:
                timeout = None if self.ending else max(
                    0.01, self.keepalive_interval - (time.monotonic() - self.last_sent)
                )
                raw = await asyncio.wait_for(self.socket.recv(), timeout)
                return self.parse(raw)
            except asyncio.TimeoutError:
                async with self.send_lock:
                    if not self.ending and time.monotonic() - self.last_sent >= self.keepalive_interval:
                        await self.socket.send('{"type":"keepalive"}')
                        self.last_sent = time.monotonic()

    async def close(self):
        if self.socket:
            await self.socket.close()
