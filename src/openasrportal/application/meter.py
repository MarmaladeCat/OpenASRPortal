"""Serialize token-limited streams and debit cumulative usage by differences."""

import asyncio

from ..storage.usage import reported_tokens


class SessionMeter:
    def __init__(self, usage, identity, locks):
        self.usage, self.identity, self.locks = usage, identity, locks
        self.acquired = []
        self.event = None
        self.scopes = {}

    async def start(self, *, deferred=False):
        with self.usage.store.connection() as db:
            session = self.usage.session(db, self.identity)
            scopes = [("key", session["key_id"]), ("profile", session["profile_id"])]
            limited = [pair for pair in scopes if pair[1] and
                       self.usage.account(db, *pair)["remaining_tokens"] is not None]
        for pair in limited:
            lock = self.locks.setdefault(pair, asyncio.Lock())
            await lock.acquire()
            self.acquired.append(lock)
        if not deferred:
            self.begin()

    def begin(self, *, accepted_audio=False):
        if self.event is None:
            self.event = self.usage.begin_call(self.identity, tokens=True, accepted_audio=accepted_audio)

    def response(self, payload, final=False):
        usage = reported_tokens(payload)
        if usage is not None or final:
            self.usage.complete_call(self.event, usage, final=final)

    def scoped(self, report, final=False):
        self.scopes[report.scope] = self.usage.report_provider_usage(self.identity, report)
        values = list(self.scopes.values())
        known = [value for value in values if value.kind == "tokens"]
        complete = bool(known) and len(known) == len(values)
        if known:
            tokens = {"total": sum(value.total for value in known),
                      "input": sum(value.input for value in known) if all(value.input is not None for value in known) else None,
                      "output": sum(value.output for value in known) if all(value.output is not None for value in known) else None}
            self.usage.complete_call(self.event, tokens, final=final and complete)
        if final and not complete:
            self.usage.complete_call(self.event, None)

    def close(self):
        for lock in reversed(self.acquired):
            lock.release()
        self.acquired.clear()
