"""Bounded in-memory recordings and HTTP bodies with a real write barrier."""

import asyncio
import base64
import struct

from aiohttp.payload import Payload

from ..domain.asr_protocol import ProviderError


class RecordingBudget:
    def __init__(self, capacity=64 * 1024 * 1024):
        self.capacity, self.reserved = capacity, 0

    def reserve(self, size):
        if self.reserved + size > self.capacity:
            raise ProviderError("完整录音缓存容量已满", code="UPSTREAM_BUSY")
        self.reserved += size


class Recording:
    def __init__(self, budget, limit):
        self.budget, self.limit = budget, limit
        self.chunks, self.size, self.reserved = [], 0, False
        self.sealed = False

    def open(self):
        self.budget.reserve(self.limit)
        self.reserved = True

    def append(self, pcm):
        if not self.reserved or self.sealed or len(pcm) % 2 or self.size + len(pcm) > self.limit:
            raise ProviderError("完整录音超过有效上限或已经结束", code="AUDIO_LIMIT", retryable=False)
        if pcm:
            self.chunks.append(bytes(pcm))
            self.size += len(pcm)

    def close(self):
        self.chunks.clear()
        if self.reserved:
            self.budget.reserved -= self.limit
            self.reserved = False

    def wav(self):
        yield struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + self.size, b"WAVE", b"fmt ",
                          16, 1, 1, 16000, 32000, 2, 16, b"data", self.size)
        yield from self.chunks


class DataUriBody(Payload):
    """Known Content-Length: the final byte plus drain is the upload boundary.

    No chunked framing or generator-yield receipt. Encoding uses a <=2-byte
    carry across WAV/chunk boundaries and never copies the whole recording.
    """

    def __init__(self, recording, prefix, suffix):
        super().__init__(None, content_type="application/json")
        self.recording, self.prefix, self.suffix = recording, prefix, suffix
        self._size = len(prefix) + len(suffix) + ((44 + recording.size + 2) // 3) * 4
        self.submitted = asyncio.Event()

    def decode(self, encoding="utf-8", errors="strict"):
        raise TypeError("An audio request body cannot be decoded as text")

    async def write(self, writer):
        await writer.write(self.prefix)
        carry = b""
        for chunk in self.recording.wav():
            data = carry + chunk
            end = len(data) - len(data) % 3
            if end:
                await writer.write(base64.b64encode(data[:end]))
            carry = data[end:]
        if carry:
            await writer.write(base64.b64encode(carry))
        await writer.write(self.suffix)
        await writer.drain()
        self.submitted.set()
        self.recording.close()
