"""Soniox real-time tokens: stable prefix plus a replaceable provisional suffix."""

import asyncio
import json
import time

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import ResultEmitter
from .base import StreamingProvider
from .transport import connect


class SonioxProvider(StreamingProvider):
    label = "Soniox"
    text_processing = "native"
    finish_timeout = 30
    keepalive_interval = 10

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.ending = False
        self.send_lock = asyncio.Lock()
        self.results = ResultEmitter()
        self.order = 0
        self.last_sent = time.monotonic()

    def parameters(self):
        result = {"model": self.config["model"], "audio_format": "pcm_s16le",
                   "sample_rate": 16000, "num_channels": 1,
                  "enable_endpoint_detection": self.config.get("endpointDetection", False)}
        if result["enable_endpoint_detection"]:
            result["max_endpoint_delay_ms"] = self.config["endpointDelayMs"]
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
            raise ProviderError.upstream("Soniox", error.status_code) from None
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

    def replace(self, tokens, stable=False):
        events = self.results.replace(
            f"tokens:{self.order}", self.order, "".join(token["text"] for token in tokens),
            stable=stable, start=tokens[0].get("start_ms") if tokens else None,
            end=tokens[-1].get("end_ms") if tokens else None, source="soniox",
        )
        if stable:
            self.order += 1
        return events

    def close_tail(self):
        if f"tokens:{self.order}" in self.results.results:
            return self.replace([], stable=True)
        return []

    def parse(self, raw):
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError()
            if message.get("error_code") or message.get("error_type"):
                raise ProviderError.upstream("Soniox", message.get("error_code"), message.get("error_type"))
            tokens = message.get("tokens", [])
            if not isinstance(tokens, list):
                raise ValueError()
            events, stable, provisional = [], [], []
            for token in tokens:
                text, final = token["text"], token["is_final"]
                if not isinstance(text, str) or type(final) is not bool:
                    raise ValueError()
                if text in ("<end>", "<fin>"):
                    if not final or provisional:
                        raise ValueError()
                    if stable:
                        events.extend(self.replace(stable, stable=True))
                        stable = []
                    events.extend(self.close_tail())
                    continue
                if final and provisional:
                    raise ValueError()
                for field in ("start_ms", "end_ms"):
                    value = token.get(field)
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError()
                if final:
                    stable.append(token)
                else:
                    provisional.append(token)
            # Soniox final tokens are ordered additions; non-final tokens replace
            # the complete suffix. Text equality is never a deduplication signal.
            if stable:
                events.extend(self.replace(stable, stable=True))
            finished = message.get("finished") is True
            if finished:
                if not self.ending or provisional:
                    raise ValueError()
                events.extend(self.close_tail())
                self.results.finish()
            elif "tokens" in message:
                if provisional or f"tokens:{self.order}" in self.results.results:
                    events.extend(self.replace(provisional))
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
