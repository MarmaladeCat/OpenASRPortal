"""Serialize token-limited streams and debit cumulative usage by differences."""

import asyncio

from ..storage.usage import reported_tokens


class SessionMeter:
    def __init__(self, usage, identity, locks):
        self.usage, self.identity, self.locks = usage, identity, locks
        self.acquired = []
        self.event = None

    async def start(self):
        with self.usage.store.connection() as db:
            session = self.usage.session(db, self.identity)
            scopes = [("key", session["key_id"]), ("profile", session["profile_id"])]
            limited = [pair for pair in scopes if pair[1] and
                       self.usage.account(db, *pair)["remaining_tokens"] is not None]
        for pair in limited:
            lock = self.locks.setdefault(pair, asyncio.Lock())
            await lock.acquire()
            self.acquired.append(lock)
        self.event = self.usage.begin_call(self.identity, tokens=True)

    def response(self, payload, final=False):
        usage = reported_tokens(payload)
        if usage is not None or final:
            self.usage.complete_call(self.event, usage, final=final)

    def close(self):
        for lock in reversed(self.acquired):
            lock.release()
        self.acquired.clear()
