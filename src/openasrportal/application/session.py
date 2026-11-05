"""In-memory recognition lease and serialized event delivery."""

import asyncio
from dataclasses import dataclass, field


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

    async def emit(self, kind, **fields):
        if self.ws is not None and self.ws.prepared and not self.ws.closed:
            async with self.lock:
                await self.ws.send_json(self.stream.event(kind, **fields))
