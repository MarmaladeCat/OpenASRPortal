"""One recognition run: ordered results, bounded audio and independent deadlines."""

import asyncio
import logging

from ..diagnostics import checkpoint, mark, span
from ..domain.asr_protocol import ProviderError
from ..providers.registry import AUDIO
from ..storage.usage import UsageError
from .meter import SessionMeter


def failure(code, message):
    return ProviderError(message, code=code, retryable=code not in {
        "INVALID_STATE", "UNSUPPORTED_AUDIO", "AUDIO_LIMIT", "UPSTREAM_PROTOCOL_ERROR",
    })


class RecognitionSession:
    def __init__(self, session, provider, store, billing_locks, recording_timeout=300):
        self.session, self.provider, self.store = session, provider, store
        self.billing_locks = billing_locks
        self.recording_timeout = min(recording_timeout, session.limits["maxRecordingMs"] / 1000)
        self.queue = asyncio.Queue()
        self.queued_bytes = 0
        self.input_ended = asyncio.Event()
        self.submitted = asyncio.Event()
        self.provider_done = asyncio.Event()
        self.meter = None
        self.tasks = []
        self.deferred_request = getattr(provider, "deferred_request", False)

    async def audio(self, pcm):
        session = self.session
        async with session.lock:
            if session.quota_scope:
                return  # Documented in-flight discard after automatic quota end.
            if session.state != "RECEIVING":
                raise failure("INVALID_STATE", "当前状态不能发送音频")
            if len(pcm) % 2:
                raise failure("UNSUPPORTED_AUDIO", "PCM16 字节数必须为偶数")
            if (session.accepted_samples + len(pcm) // 2) * 1000 > session.limits["maxRecordingMs"] * 16000:
                raise failure("AUDIO_LIMIT", "录音超过本轮有效上限")
            if self.queued_bytes + len(pcm) > session.limits["maxQueuedAudioBytes"]:
                raise failure("UPSTREAM_BUSY", "上游音频积压超过有效上限，请稍后重试")
            try:
                accepted, scope = self.store.usage.accept_audio(session.id, len(pcm))
            except UsageError as error:
                if error.code not in ("QUOTA_EXHAUSTED", "PROFILE_DISABLED"):
                    raise
                accepted, scope = 0, "account"
            if accepted:
                mark("firstClientAudioReceived")
                session.accepted_samples += accepted // 2
                self.queued_bytes += accepted
                self.queue.put_nowait(pcm[:accepted])
            if scope:
                session.quota_scope = scope
                self._end()

    def _end(self):
        self.session.state = "DRAINING"
        self.input_ended.set()
        self.queue.put_nowait(None)
        mark("audioEndReceived")

    async def end(self):
        async with self.session.lock:
            if self.session.state in {"DRAINING", "FINALIZING"}:
                return
            if self.session.state != "RECEIVING":
                raise failure("INVALID_STATE", "当前状态不能结束音频")
            self._end()

    async def initialize(self):
        if getattr(self.provider, "token_metered", False):
            self.meter = SessionMeter(self.store.usage, self.session.id, self.billing_locks)
            self.provider.usage_callback = self.meter.scoped if getattr(self.provider, "scoped_usage", False) else self.meter.response
            await asyncio.wait_for(self.meter.start(deferred=self.deferred_request), 20)
        with span("providerOpen"):
            await asyncio.wait_for(self.provider.open(), 20)

    async def upload(self):
        pending = bytearray()

        async def write(pcm):
            try:
                await asyncio.wait_for(self.provider.write_audio(pcm), 15)
            except asyncio.TimeoutError:
                raise failure("UPLOAD_TIMEOUT", "上游音频提交超时") from None
            self.queued_bytes -= len(pcm)
            mark("firstUpstreamAudioSent")

        while True:
            pcm = await self.queue.get()
            if pcm is None:
                if pending:
                    await write(bytes(pending))
                if self.session.accepted_samples:
                    if self.deferred_request:
                        if self.meter:
                            self.meter.begin(accepted_audio=True)
                        else:
                            self.store.usage.begin_call(self.session.id, accepted_audio=True)
                    # Includes private uploader drain, resampler tail and actual
                    # WS commit / HTTP request body completion, not queue receipt.
                    await self.provider.finish_input()
                self.session.submitted_samples = self.session.accepted_samples
                self.submitted.set()
                self.session.state = "FINALIZING"
                if not self.session.accepted_samples:
                    self.provider_done.set()
                await asyncio.Future()
            pending.extend(pcm)
            while len(pending) >= 6400:
                await write(bytes(pending[:6400]))
                del pending[:6400]

    async def download(self):
        while True:
            events, last = await self.provider.receive()
            finals = await self.session.apply(events)
            for event in finals:
                try:
                    await asyncio.to_thread(self.store.hotwords.observe, self.session.owner, event)
                except Exception:
                    logging.getLogger(__name__).error("热词统计失败，识别会话继续")
            if last:
                if not self.input_ended.is_set():
                    raise failure("UPSTREAM_CLOSED", "上游提前结束，尚未完成音频提交")
                self.session.stream.finish()
                self.provider_done.set()
                await asyncio.Future()

    async def finalize(self):
        try:
            await asyncio.wait_for(self.input_ended.wait(), self.recording_timeout)
        except asyncio.TimeoutError:
            raise failure("SESSION_TIMEOUT", "录音等待超过本轮有效上限") from None
        try:
            await asyncio.wait_for(self.submitted.wait(), self.session.limits["uploadTimeoutMs"] / 1000)
        except asyncio.TimeoutError:
            raise failure("UPLOAD_TIMEOUT", "音频缓存提交超时") from None
        try:
            await asyncio.wait_for(self.provider_done.wait(), self.provider.finish_timeout)
        except asyncio.TimeoutError:
            raise failure("FINALIZATION_TIMEOUT", "等待最终定稿超时") from None
        self.session.stream.finish()

    async def run(self, controls):
        session = self.session
        session.state = "CONNECTING"
        reader, startup = asyncio.create_task(controls()), asyncio.create_task(self.initialize())
        self.tasks = [reader, startup]
        done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            reader.result()
            return
        startup.result()
        if session.cancelled or session.terminal:
            return
        if not self.meter and not self.deferred_request:
            self.store.usage.begin_call(session.id)
        await session.emit(
            "session.ready", _state="RECEIVING", audio=AUDIO,
            profileId=session.profile["id"], capabilities=session.capabilities,
            limits=session.limits, textProcessing=self.provider.text_processing,
            finalizeTimeoutMs=session.limits["finalizeTimeoutMs"], hotwords=session.hotword_selection,
        )
        mark("readySent")
        checkpoint("ready")
        self.tasks = [reader, asyncio.create_task(self.upload()),
                      asyncio.create_task(self.download()), asyncio.create_task(self.finalize())]
        done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if session.cancelled or session.terminal:
            return
        await session.emit(
            "session.finished", finalCount=session.stream.final_count,
            acceptedAudioSamples=session.accepted_samples, submittedAudioSamples=session.submitted_samples,
            **({"reason": "quota_exhausted", "quotaScope": session.quota_scope,
                "truncated": True} if session.quota_scope else {}),
        )
        mark("finishedSent")

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(self.provider.close(), 5)
        finally:
            if self.meter:
                self.meter.close()
