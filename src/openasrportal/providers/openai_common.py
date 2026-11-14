"""OpenAI-only configuration, error and usage semantics shared by its two paths."""

import json

from ..domain.asr_protocol import ProviderError
from ..domain.provider_usage import UsageUpdate
from ..domain.transcript import protocol_error


def parse(raw):
    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise protocol_error() from None
    if event.get("type") in {"error", "conversation.item.input_audio_transcription.failed"} or "error" in event:
        detail = event.get("error", {})
        if not isinstance(detail, dict):
            detail = {}
        raise ProviderError.upstream("OpenAI", detail.get("code"), detail.get("type"))
    return event


def context(config):
    result = {"model": config["model"]}
    if config.get("prompt"):
        result["prompt"] = config["prompt"]
    if config.get("languages"):
        result["languages"] = config["languages"].split(",")
    if config.get("hotwords"):
        result["keywords"] = [item["text"] for item in config["hotwords"]]
    if config.get("delay") and config["model"] == "gpt-live-transcribe":
        result["delay"] = config["delay"]
    return result


def usage(event, scope):
    value = event.get("usage")
    if value is None:
        return UsageUpdate(scope, "unknown", None)
    if not isinstance(value, dict):
        raise protocol_error()
    if value.get("type") == "duration":
        return UsageUpdate(scope, "duration", value.get("seconds"))
    if value.get("type") == "tokens":
        return UsageUpdate(scope, "tokens", value.get("total_tokens"),
                           value.get("input_tokens"), value.get("output_tokens"))
    raise protocol_error()
