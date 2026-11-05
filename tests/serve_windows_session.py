"""Real Portal with delayed synthetic ASR and text model; loopback test data only."""

import asyncio
import json
import tempfile
from pathlib import Path

from aiohttp import web
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.storage.store import Store


async def main():
    results = Path(__file__).resolve().parents[1] / "test-results"
    results.mkdir(exist_ok=True)
    stats = {"audioBytes": 0, "sessions": 0, "edits": 0, "closed": 0}

    class Provider(FakeProvider):
        async def open(self):
            stats["sessions"] += 1
            await asyncio.sleep(1.5)
            await super().open()

        async def send_audio(self, data, last=False):
            stats["audioBytes"] += len(data)
            await super().send_audio(data, last)

        async def close(self):
            stats["closed"] += 1
            await super().close()

    async def edit(request):
        if request.headers.get("Authorization") != "Bearer test-text":
            raise web.HTTPUnauthorized()
        body = await request.json()
        if body.get("model") != "test-model":
            raise web.HTTPBadRequest()
        content = json.loads(body["messages"][-1]["content"])
        if content != {"instruction": "最终文本。", "selectedText": "原文🙂"}:
            raise web.HTTPBadRequest()
        stats["edits"] += 1
        return web.json_response(
            {"choices": [{"message": {"content": "修改完成🙂"}, "finish_reason": "stop"}]}
        )

    async def status(request):
        return web.json_response(stats)

    with tempfile.TemporaryDirectory(prefix="windows-session-", dir=results) as directory:
        store = Store(directory)
        store.save("test", "Windows fixture", "openlocalasr", {"apiKey": "test-upstream"})
        portal = Portal(store, "test-asr", "test-admin", factory=Provider)
        app = portal.app()
        app.router.add_post("/chat/completions", edit)
        app.router.add_get("/fixture/status", status)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        print(
            json.dumps({"url": f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"}),
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
