"""In-memory recognition lease and serialized event delivery."""

import asyncio
from dataclasses import dataclass, field

from ..diagnostics import mark


@dataclass
class Session:
    id: str
    owner: str
    profile: dict
    ticket: str
    expires: float
    request_id: str
    ws: object = None
    cancelled: bool = False
    stream: object = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    quota_scope: str | None = None
    hotword_selection: dict = field(default_factory=dict)
    request_spec: tuple = ()
    terminal: bool = False
    state: str = "CREATED"
    capabilities: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    accepted_samples: int = 0
    submitted_samples: int | None = None

    async def emit(self, kind, *, _state=None, **fields):
        if self.ws is not None and self.ws.prepared and not self.ws.closed:
            async with self.lock:
                if self.terminal:
                    return
                if kind in {"session.finished", "session.cancelled", "session.error"}:
                    self.terminal = True
                    self.state = "TERMINAL"
                elif _state:
                    self.state = _state
                await asyncio.wait_for(self.ws.send_json(self.stream.event(kind, **fields)), 5)

    async def apply(self, events):
        finals = []
        async with self.lock:
            if self.cancelled or self.terminal:
                return finals
            for event in self.stream.apply(events):
                if event["text"]:
                    mark("firstTranscript")
                    if event["type"] == "transcript.final":
                        mark("firstFinal")
                await asyncio.wait_for(self.ws.send_json(event), 5)
                if event["type"] == "transcript.final":
                    finals.append(event)
        return finals
