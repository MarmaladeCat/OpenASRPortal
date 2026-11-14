"""Production provider definitions: construction, effective capabilities and limits."""

from dataclasses import dataclass

from ..domain.config import config_defaults, validate_config
from ..domain.hotwords import capability
from .bailian_asr import BailianProvider
from .boson_asr import BosonProvider
from .dashscope_asr import DashScopeProvider
from .doubao_asr import DoubaoProvider
from .localasr_file import LocalASRFileProvider
from .openai_file import OpenAIFileProvider
from .openai_realtime import OpenAIRealtimeProvider
from .soniox_asr import SonioxProvider

AUDIO = {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1}


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    factory: type
    processing: str
    preview: str
    stability: str
    triggers: tuple
    completion: str = "upstream_done"
    input: str = "continuous"
    max_recording_ms: int = 300000

    def defaults(self):
        return config_defaults(self.name)

    def validate(self, patch, previous=None):
        return validate_config(self.name, patch, previous)

    def limits(self):
        return {
            "maxRecordingMs": self.max_recording_ms, "maxMessageBytes": 1024 * 1024,
            "maxQueuedAudioBytes": 32000 * 60, "readyTimeoutMs": 45000,
            "uploadTimeoutMs": 75000, "recognitionTimeoutMs": int(self.factory.finish_timeout * 1000),
            "finalizeTimeoutMs": int((self.factory.finish_timeout + 76) * 1000),
        }

    def capabilities(self, configuration):
        second_pass = {"support": "unknown", "enabled": None}
        processing = self.processing
        preview, completion = self.preview, self.completion
        if self.name == "openai_file" and configuration.get("responseMode", "json") == "sse":
            preview, completion = "after_audio_end", "sse_done"
        if self.name == "openai_realtime" and configuration.get("model") == "gpt-transcribe":
            preview = "after_commit"
        if self.name == "doubao_realtime":
            enabled = configuration.get("enableNonstream", False)
            second_pass = {"support": "supported", "enabled": enabled}
            processing = "online_with_second_pass" if enabled else "online"
        recognition = {
            "upstreamInput": self.input, "processingMode": processing,
            "preview": {"supported": preview != "none", "phase": preview},
            "stability": {"unit": self.stability, "triggers": list(self.triggers)},
            "completion": completion, "sessionEnd": "audio.end",
            "portalSegmentation": "none", "secondPass": second_pass,
        }
        return {
            "recognition": recognition, "limits": self.limits(),
            "partialResults": preview != "none", "textProcessing": "native",
            "latencyClass": "streaming" if preview == "during_capture" else "segmented",
            "finalization": "audio.end" if self.stability in {"turn", "recording"} else "upstream",
            "localSegmentation": False, "audio": dict(AUDIO),
            "tokenUsage": bool(getattr(self.factory, "token_metered", False)),
            "hotwords": capability(self.name),
        }


DEFINITIONS = {item.name: item for item in (
    ProviderDefinition("doubao_realtime", DoubaoProvider, "online", "during_capture",
                       "utterance", ("upstream_endpoint",)),
    ProviderDefinition("bailian_qwen_asr", BailianProvider, "online", "during_capture",
                       "utterance", ("upstream_endpoint",)),
    ProviderDefinition("openlocalasr", DashScopeProvider, "unknown", "unknown",
                       "utterance", ("upstream_endpoint",)),
    ProviderDefinition("openlocalasr_file", LocalASRFileProvider, "batch", "none",
                       "recording", ("audio_end",), "http_response", "complete_recording", 60000),
    ProviderDefinition("soniox_realtime", SonioxProvider, "online", "during_capture",
                       "token", ("upstream_stable",)),
    ProviderDefinition("boson_realtime", BosonProvider, "unknown", "none",
                       "turn", ("audio_end",), "committed_items"),
    ProviderDefinition("openai_file", OpenAIFileProvider, "batch", "none",
                       "recording", ("audio_end",), "http_response", "complete_recording"),
    ProviderDefinition("openai_realtime", OpenAIRealtimeProvider, "unknown", "during_capture",
                       "turn", ("client_commit",), "committed_items"),
)}
PROVIDERS = {name: definition.factory for name, definition in DEFINITIONS.items()}


def definition(name):
    try:
        return DEFINITIONS[name]
    except KeyError:
        raise ValueError("未知的远程 ASR 提供商") from None
