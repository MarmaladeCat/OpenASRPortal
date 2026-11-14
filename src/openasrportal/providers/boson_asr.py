"""Higgs Realtime input transcription, with manual turns and no generated replies.

Every PCM sample, including silence, is streamed as it arrives. Only audio.end
commits the recording; transport chunk sizes are never sentence boundaries.
No speculative text is emitted.
"""

import asyncio
import base64
import json
import logging
import time
import uuid

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import ResultEmitter
from .base import StreamingProvider
from .transport import connect

BYTES_PER_SECOND = 32000
MAX_QUEUED_BYTES = 15 * BYTES_PER_SECOND
LOGGER = logging.getLogger(__name__)


class BosonProvider(StreamingProvider):
    label = "Boson AI"
    text_processing = "native"
    finish_timeout = 35

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.worker = None
        self.uploader = None
        self.audio = asyncio.Queue(maxsize=128)
        self.queued_bytes = 0
        self.input_ended = False
        self.events = asyncio.Queue(maxsize=32)
        self.completed = asyncio.Event()
        self.completed.set()
        self.pending = None
        self.failure = None
        self.results = ResultEmitter()
        self.ending = False
        self.closed = False
        self.total = self.start = 0
        self.outgoing = bytearray()
        self.trace_id = uuid.uuid4().hex[:12]
        self.segment_number = 0

    async def _send(self, kind, **fields):
        await self.socket.send(json.dumps({"type": kind, **fields}))

    def _parse(self, raw):
        try:
            event = json.loads(raw)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ValueError
        except (ValueError, TypeError):
            raise ProviderError("Boson AI 返回了无效的实时事件") from None
        if event["type"] in (
            "error", "conversation.item.input_audio_transcription.failed",
            "session.idle_timeout", "session.max_duration_reached",
        ):
            # Never expose arbitrary upstream messages, which may echo input or keys.
            detail = event.get("error")
            detail = detail if isinstance(detail, dict) else {}
            raise ProviderError.upstream("Boson AI", detail.get("code"), detail.get("type"))
        return event

    async def open(self):
        started = time.monotonic()
        try:
            self.socket = await connect(
                self.config["endpoint"],
                use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                extra_headers={"Authorization": "Bearer " + self.config["apiKey"]},
                open_timeout=6, close_timeout=1, max_size=4 * 1024 * 1024,
            )
        except InvalidStatusCode as error:
            raise ProviderError.upstream("Boson AI", error.status_code) from None
        transcription = {"model": self.config["model"]}
        if self.config["language"] != "auto":
            transcription["language"] = self.config["language"]
        # Boson sends session.created only AFTER this first update.
        await self._send("session.update", session={
            "type": "realtime", "model": "higgs-realtime", "output_modalities": ["text"],
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 16000},
                "transcription": transcription, "turn_detection": None,
            }},
        })
        event = self._parse(await asyncio.wait_for(self.socket.recv(), 8))
        if event["type"] != "session.created":
            raise ProviderError("Boson AI 未确认转写会话启动")
        LOGGER.info("Boson timing session=%s ready_ms=%.1f", self.trace_id, (time.monotonic() - started) * 1000)
        self.worker = asyncio.create_task(self._read())
        self.uploader = asyncio.create_task(self._upload())

    async def _flush(self):
        if self.outgoing:
            await self._send(
                "input_audio_buffer.append",
                audio=base64.b64encode(self.outgoing).decode("ascii"),
            )
            self.outgoing.clear()

    async def _commit(self):
        await self._flush()
        self.segment_number += 1
        self.pending = {"start": self.start // 32, "end": self.total // 32, "id": None,
                        "committed_at": time.monotonic()}
        LOGGER.info(
            "Boson timing session=%s segment=%d commit audio_start_ms=%d audio_end_ms=%d queued_ms=%d",
            self.trace_id, self.segment_number, self.pending["start"], self.pending["end"], self.queued_bytes // 32,
        )
        self.completed.clear()
        await self._send("input_audio_buffer.commit")

    async def _wait_pending(self):
        if self.failure:
            raise self.failure
        if not self.completed.is_set():
            await asyncio.wait_for(self.completed.wait(), 30)
        if self.failure:
            raise self.failure

    async def probe(self):
        # Validate actual model access, not just a WebSocket handshake. Its silent
        # transcript is discarded by the management probe, never sent to clients.
        # Go through send_audio so Portal's probe quota/metering wrapper sees it.
        await self.write_audio(bytes(6400))
        await self.finish_input()
        await self._wait_pending()

    async def send_audio(self, pcm, last=False):
        if self.input_ended or self.closed:
            raise ProviderError("Boson AI 录音会话已经结束")
        if len(pcm) % 2:
            raise ProviderError("音频必须为 16 kHz 单声道 PCM16")
        for offset in range(0, max(1, len(pcm)), 6400):
            if self.closed:
                raise ProviderError("Boson AI 录音会话已经结束")
            if self.failure:
                raise self.failure
            chunk = bytes(pcm[offset:offset + 6400])
            # Count real backlog, not a burst that has never let the uploader run.
            # A stalled upstream still fails at a bounded queue rather than
            # blocking Portal's reader from processing cancellation.
            if self.audio.full() or self.queued_bytes + len(chunk) > MAX_QUEUED_BYTES:
                raise ProviderError("Boson AI 转写积压，请停止录音并检查网络后重试")
            self.queued_bytes += len(chunk)
            self.input_ended = last and offset + 6400 >= len(pcm)
            self.audio.put_nowait((chunk, self.input_ended))
            await asyncio.sleep(0)

    async def _upload(self):
        try:
            while True:
                pcm, last = await self.audio.get()
                await self._process_audio(pcm, last)
                self.queued_bytes -= len(pcm)
                self.audio.task_done()
                if last:
                    return
        except Exception as error:
            self.failure = error
            await self.events.put(error)

    async def finish_input(self):
        await self.send_audio(b"", last=True)
        await self.uploader
        if self.failure:
            raise self.failure

    async def _process_audio(self, pcm, last):
        for offset in range(0, len(pcm), 6400):
            chunk = pcm[offset:offset + 6400]
            self.total += len(chunk)
            self.outgoing.extend(chunk)
            await self._flush()
        if last:
            self.ending = True
            if self.total:
                await self._commit()
            else:
                await self.events.put(([], True))

    async def _read(self):
        try:
            while True:
                event = self._parse(await self.socket.recv())
                kind = event["type"]
                if kind == "input_audio_buffer.committed":
                    if self.pending is None or not isinstance(event.get("item_id"), str):
                        raise ProviderError("Boson AI 返回了不匹配的转写分段")
                    self.pending["id"] = event["item_id"]
                    LOGGER.info("Boson timing session=%s segment=%d commit_ack_ms=%.1f", self.trace_id,
                                self.segment_number, (time.monotonic() - self.pending["committed_at"]) * 1000)
                elif kind == "conversation.item.input_audio_transcription.completed":
                    identity = event.get("item_id")
                    if (self.pending is None or not identity
                            or identity != self.pending["id"]
                            or not isinstance(event.get("transcript"), str)):
                        raise ProviderError("Boson AI 返回了不匹配的转写分段")
                    text = event["transcript"]
                    LOGGER.info("Boson timing session=%s segment=%d final_after_commit_ms=%.1f queued_ms=%d",
                                self.trace_id, self.segment_number,
                                (time.monotonic() - self.pending["committed_at"]) * 1000, self.queued_bytes // 32)
                    # The sole manual turn has known order, but no word timestamps.
                    events = self.results.replace(identity, 0, text, stable=True, source="boson_realtime")
                    self.pending = None
                    await self.events.put((events, self.ending))
                    self.completed.set()
                    if self.ending:
                        return
                # Assistant text/audio and conversation.item.done are NOT STT finals.
        except Exception as error:
            self.failure = error
            self.completed.set()
            await self.events.put(error)

    async def receive(self):
        result = await self.events.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        self.closed = True
        tasks = [task for task in (self.worker, self.uploader) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.socket:
            await self.socket.close()
