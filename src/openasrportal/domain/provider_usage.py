"""Confirmed supplier usage, scoped to a request/item rather than message arrival."""

import math
from dataclasses import dataclass

from .transcript import protocol_error


def reported_usage(payload):
    """Find a supplier's usage object without conflating invalid with absent."""
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            break
        if current.get("usage") is not None:
            return current["usage"]
        current = current.get("output")
    return None


@dataclass(frozen=True)
class UsageUpdate:
    scope: str
    kind: str
    total: int | float | None
    input: int | None = None
    output: int | None = None

    def __post_init__(self):
        if (not isinstance(self.scope, str) or not 1 <= len(self.scope) <= 512
                or self.kind not in {"tokens", "duration", "unknown"}):
            raise protocol_error()
        if self.kind == "unknown":
            if self.total is not None:
                raise protocol_error()
        elif (type(self.total) not in (int, float) or not math.isfinite(self.total)
              or not 0 <= self.total <= 2**53 or (self.kind == "tokens" and type(self.total) is not int)):
            raise protocol_error()
        for value in (self.input, self.output):
            if value is not None and (type(value) is not int or not 0 <= value <= 2**53):
                raise protocol_error()
