"""Independent complete-recording lifecycle; providers implement one request."""

import asyncio

from ..domain.asr_protocol import ProviderError
from .file_audio import Recording, RecordingBudget


class BufferedFileProvider:
    deferred_request = True
    text_processing = "native"
    finish_timeout = 60
    max_audio_bytes = 60 * 32000

    def __init__(self, config):
        self.config = config
        self.recording = Recording(config.get("_recordingBudget") or RecordingBudget(), self.max_audio_bytes)
        self.request = None
        self.body = None
        self.events = asyncio.Queue(maxsize=32)
        self.request_started = asyncio.Event()
        self.input_submitted = asyncio.Event()

    async def open(self):
        self.recording.open()

    async def write_audio(self, pcm):
        self.recording.append(pcm)

    async def finish_input(self):
        if self.recording.sealed:
            raise ProviderError("完整录音已经提交", code="INVALID_STATE", retryable=False)
        self.recording.sealed = True
        self.body = self.make_body()
        self.request = asyncio.create_task(self.recognize(self.body))
        self.request_started.set()
        receipt = asyncio.create_task(self.body.submitted.wait())
        try:
            done, _ = await asyncio.wait((self.request, receipt), return_when=asyncio.FIRST_COMPLETED)
            if self.request in done:
                self.request.result()
                if not self.body.submitted.is_set():
                    raise ProviderError("上游在完整音频提交前结束响应", code="UPSTREAM_PROTOCOL_ERROR")
            self.input_submitted.set()
        finally:
            receipt.cancel()
            await asyncio.gather(receipt, return_exceptions=True)

    async def receive(self):
        # Request exceptions must also reach the result reader after submission.
        await self.input_submitted.wait()
        ready = asyncio.create_task(self.events.get())
        try:
            # The receiver may start while capture is still in progress.
            while self.request is None:
                await self.request_started.wait()
            done, _ = await asyncio.wait((ready, self.request), return_when=asyncio.FIRST_COMPLETED)
            if self.request in done:
                self.request.result()
            return await ready
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)

    async def send_audio(self, pcm, last=False):
        await self.write_audio(pcm)
        if last:
            await self.finish_input()

    async def cancel(self):
        await self.close()

    async def close(self):
        if self.request:
            self.request.cancel()
            await asyncio.gather(self.request, return_exceptions=True)
        self.recording.close()
