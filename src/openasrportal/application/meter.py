"""Serialize token-limited upstream calls and settle their actual usage."""

import asyncio
from contextlib import asynccontextmanager

from ..storage.usage import UsageError, reported_tokens


class SessionMeter:
    def __init__(self, usage, identity, locks):
        self.usage, self.identity, self.locks = usage, identity, locks

    def reserve_final(self, byte_count):
        self.usage.shrink_reservation(self.identity, byte_count)

    @asynccontextmanager
    async def request(self, byte_count, final=True):
        acquired = []
        event = None
        completed = False
        try:
            with self.usage.store.connection() as db:
                session = self.usage.session(db, self.identity)
                scopes = [("key", session["key_id"]), ("profile", session["profile_id"])]
                limited = [
                    pair
                    for pair in scopes
                    if pair[1] and self.usage.account(db, *pair)["remaining_tokens"] is not None
                ]
            for pair in limited:
                lock = self.locks.setdefault(pair, asyncio.Lock())
                await lock.acquire()
                acquired.append(lock)
            event = self.usage.begin_call(self.identity, byte_count, final=final, snapshot=True)

            def response(payload):
                nonlocal completed
                completed = True
                if event:
                    self.usage.complete_call(event, reported_tokens(payload))

            yield (event, response)
        finally:
            try:
                if event and not completed:
                    try:
                        self.usage.complete_call(event, None)
                    except UsageError:
                        pass
            finally:
                for lock in reversed(acquired):
                    lock.release()
