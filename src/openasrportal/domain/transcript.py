"""Provider identities and ordered, immutable recognition results (no I/O)."""

import math
from dataclasses import dataclass

from .asr_protocol import ProviderError

MAX_UNITS = 4096
MAX_TEXT = 262144


def protocol_error():
    return ProviderError("上游识别结果身份、顺序或定稿状态无效", code="UPSTREAM_PROTOCOL_ERROR",
                         retryable=False)


@dataclass(frozen=True)
class ProviderEvent:
    """A complete replacement for one logical unit, in dense audio order from zero.

    Identity is scoped to the provider run. The adapter supplies order from its
    protocol, never from completion arrival time. Stable includes explicit empty
    results/withdrawals. Transport completion is separate from result stability.
    """

    identity: str
    order: int
    revision: int
    text: str
    stable: bool = False
    start_ms: int | float | None = None
    end_ms: int | float | None = None
    source: str = ""

    def __post_init__(self):
        if (not isinstance(self.identity, str) or not 1 <= len(self.identity) <= 512
                or type(self.order) is not int or not 0 <= self.order < MAX_UNITS
                or type(self.revision) is not int or self.revision < 1
                or not isinstance(self.text, str) or len(self.text) > MAX_TEXT
                or type(self.stable) is not bool or not isinstance(self.source, str)):
            raise protocol_error()
        for value in (self.start_ms, self.end_ms):
            if value is not None and (type(value) not in (int, float)
                                      or not math.isfinite(value) or value < 0):
                raise protocol_error()

    def legacy(self):
        """Serialization only for the standalone legacy bridge, not the v1 core."""
        return {"type": "final_result" if self.stable else "partial_result", "source": self.source,
                "nbest": [{"sentence": self.text, "word_pieces": [
                    {"word": self.text, "start": self.start_ms, "end": self.end_ms}]}]}


class ResultEmitter:
    """Shared revision/deduplication rules; adapters retain ownership of identities."""

    def __init__(self):
        self.results = {}

    def replace(self, identity, order, text, *, stable=False, start=None, end=None, source=""):
        previous = self.results.get(identity)
        event = ProviderEvent(identity, order, previous.revision + 1 if previous else 1,
                              text, stable, start, end, source)
        if previous:
            if previous.order != order:
                raise protocol_error()
            if previous.stable:
                if text != previous.text or not stable:
                    raise protocol_error()
                return []
            if (previous.text, previous.stable, previous.start_ms, previous.end_ms, previous.source) == (
                    text, stable, start, end, source):
                return []
        elif len(self.results) >= MAX_UNITS:
            raise protocol_error()
        self.results[identity] = event
        return [event]

    def finish(self):
        if any(not item.stable for item in self.results.values()):
            raise protocol_error()


class TranscriptLedger:
    """Identity checks and an order barrier independent of timestamp availability."""

    def __init__(self):
        self.units = {}
        self.positions = {}
        self.frontier = 0
        self.text_size = 0

    def accept(self, event):
        if not isinstance(event, ProviderEvent):
            raise protocol_error()
        previous = self.units.get(event.identity)
        if previous:
            if event.order != previous.order:
                raise protocol_error()
            if previous.stable:
                if event.text != previous.text or not event.stable:
                    raise protocol_error()
                return
            if event.revision < previous.revision:
                return
            if event.revision == previous.revision:
                if event != previous:
                    raise protocol_error()
                return
        elif event.order in self.positions or event.order < self.frontier:
            raise protocol_error()
        size = self.text_size + len(event.text) - (len(previous.text) if previous else 0)
        if size > MAX_TEXT or len(self.units) + (previous is None) > MAX_UNITS:
            raise protocol_error()
        self.units[event.identity] = event
        self.positions[event.order] = event.identity
        self.text_size = size

    def stable_prefix(self):
        result = []
        while self.frontier in self.positions:
            item = self.units[self.positions[self.frontier]]
            if not item.stable:
                break
            result.append(item)
            self.frontier += 1
        return result

    def tail(self):
        # An unknown predecessor cannot be silently treated as silence.
        result, position = [], self.frontier
        while position in self.positions:
            result.append(self.units[self.positions[position]])
            position += 1
        return result

    def finish(self):
        if self.frontier != len(self.units) or any(not item.stable for item in self.units.values()):
            raise protocol_error()
