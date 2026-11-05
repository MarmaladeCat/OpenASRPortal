"""Disposable admin browser fixture, no upstream connections or real credentials."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from aiohttp import web
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.storage.store import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session-seconds", type=int, default=1800)
    args = parser.parse_args()
    from openasrportal.storage import auth

    auth.SESSION_SECONDS = args.session_seconds
    cache = Path(__file__).resolve().parents[1] / "test-results"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="management-ui-", dir=cache) as directory:
        if args.fresh:
            from openasrportal.api.server import Portal as FreshPortal

            portal = FreshPortal(Store(directory), factory=FakeProvider)
        else:
            portal = Portal(Store(directory), "test-asr", "test-admin", factory=FakeProvider)
        runner = web.AppRunner(portal.app())
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", args.port)
        await site.start()
        print(
            json.dumps(
                {"url": "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])}
            ),
            flush=True,
        )
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
