"""Lazy, per-session continuous PCM16 conversion; no work for 16 kHz providers."""

from ..domain.asr_protocol import ProviderError


class PCM24k:
    def __init__(self):
        try:
            import numpy
            import soxr
        except ImportError:
            raise ProviderError("OpenAI Realtime 需要 numpy/soxr 音频转换组件",
                                code="UPSTREAM_CONFIGURATION", retryable=False) from None
        self.np = numpy
        # SoXR's integer output adds randomized dither. Keep the filter in float
        # and quantize once, explicitly, for reproducible PCM and exact silence.
        self.stream = soxr.ResampleStream(16000, 24000, 1, dtype="float32", quality="HQ")
        self.finished = False
        self.source_samples = self.output_samples = 0

    def convert(self, pcm, *, last=False):
        if self.finished or len(pcm) % 2:
            raise ValueError("invalid PCM conversion state")
        self.finished = last
        self.source_samples += len(pcm) // 2
        samples = self.np.frombuffer(pcm, dtype="<i2").astype(self.np.float32)
        result = self.stream.resample_chunk(samples, last=last)
        self.output_samples += len(result)
        self.np.rint(result, out=result)
        self.np.clip(result, -32768, 32767, out=result)
        return result.astype("<i2").tobytes()
