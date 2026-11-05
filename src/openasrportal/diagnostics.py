"""Opt-in, content-free startup timing for real service latency investigations."""

import asyncio
import functools
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("portal_timing", default=None)


class Timing:
    def __init__(self, kind):
        self.kind = kind
        self.started = time.perf_counter()
        self.session = ""
        self.spans = {}
        self.counts = {}
        self.marks = {}

    def emit(self, checkpoint):
        record = {
            "pid": os.getpid(),
            "kind": self.kind,
            "session": self.session,
            "checkpoint": checkpoint,
            "elapsedMs": round((time.perf_counter() - self.started) * 1000, 3),
            "spansMs": {key: round(value * 1000, 3) for key, value in self.spans.items()},
            "counts": self.counts,
            "marksMs": {key: round(value * 1000, 3) for key, value in self.marks.items()},
        }
        print("OPENASRPORTAL_TIMING " + json.dumps(record), file=sys.stderr, flush=True)


@contextmanager
def span(name):
    timing = _current.get()
    if timing is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        timing.spans[name] = timing.spans.get(name, 0) + time.perf_counter() - started
        timing.counts[name] = timing.counts.get(name, 0) + 1


def mark(name):
    timing = _current.get()
    if timing is not None:
        timing.marks.setdefault(name, time.perf_counter() - timing.started)


def session_tag(identity):
    timing = _current.get()
    if timing is not None:
        timing.session = hashlib.sha256(identity.encode()).hexdigest()[:16]


def checkpoint(name):
    timing = _current.get()
    if timing is not None:
        timing.emit(name)


def _instrument_loop(loop):
    if getattr(loop, "_openasr_timing", False):
        return
    # ContextVars attribute only this request's DNS/TCP work, even when other
    # connections run concurrently. No addresses, credentials or payloads log.
    for method, name in (("getaddrinfo", "dns"), ("sock_connect", "tcpConnect")):
        original = getattr(loop, method)

        def wrap(original, name):
            async def measured(*args, **kwargs):
                with span(name):
                    return await original(*args, **kwargs)

            return measured

        setattr(loop, method, wrap(original, name))
    loop._openasr_timing = True


def trace_request(kind):
    def decorate(function):
        @functools.wraps(function)
        async def measured(*args, **kwargs):
            if os.environ.get("OPENASRPORTAL_TIMING") != "1":
                return await function(*args, **kwargs)
            _instrument_loop(asyncio.get_running_loop())
            timing = Timing(kind)
            token = _current.set(timing)
            outcome = "done"
            try:
                return await function(*args, **kwargs)
            except BaseException:
                outcome = "interrupted"
                raise
            finally:
                _current.reset(token)
                timing.emit(outcome)

        return measured

    return decorate


def websocket_options():
    timing = _current.get()
    if timing is None:
        return {}
    from websockets.legacy.client import WebSocketClientProtocol

    class TimedProtocol(WebSocketClientProtocol):
        def connection_made(self, transport):
            timing.marks["upstreamTransportReady"] = time.perf_counter() - timing.started
            super().connection_made(transport)

        async def handshake(self, *args, **kwargs):
            with span("upstreamWebsocketHandshake"):
                return await super().handshake(*args, **kwargs)

    return {"create_protocol": TimedProtocol}
