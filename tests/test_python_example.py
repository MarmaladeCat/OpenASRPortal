"""Exercise the standalone third-party example over real loopback HTTP/WS."""

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests
from test_portal import FakeProvider

from openasrportal.storage.store import Store

spec = importlib.util.spec_from_file_location(
    "portal_example", Path(__file__).resolve().parents[1] / "examples/python/openasr_client.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class ExampleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.save("local", "Example fixture", "openlocalasr", {"apiKey": "fictional-upstream"})
        self.portal = portal_for_tests(self.store, "client-key", "admin-key", factory=FakeProvider)
        self.server = TestServer(self.portal.app())
        await self.server.start_server()

    async def asyncTearDown(self):
        await self.server.close()
        self.temp.cleanup()

    def url(self, path):
        return self.server.make_url(path)

    async def test_example_uploads_after_ready_and_returns_only_final_text(self):
        events = []
        async def chunks():
            self.assertEqual(events[0]["type"], "session.ready")
            yield bytes(6400)
            yield bytes(2)
        async with example.PortalClient(str(self.url("/")), "client-key") as client:
            text = await client.transcribe(chunks(), profile_id="local", on_event=events.append)
        self.assertEqual(text, "最终文本。")
        self.assertEqual(events[-1]["type"], "session.finished")
        self.assertNotIn("错误预览", text)

    async def test_task_cancellation_cleans_up_owned_session(self):
        started = asyncio.Event()
        async def chunks():
            started.set()
            yield bytes(640)
            await asyncio.Future()
        async with example.PortalClient(str(self.url("/")), "client-key") as client:
            task = asyncio.create_task(client.transcribe(chunks(), profile_id="local"))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.portal.sessions)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_and_websocket_redirects_never_reach_destination(self):
        visited = []
        async def destination(request):
            visited.append(request.path)
            return web.json_response({})
        target_app = web.Application()
        target_app.router.add_route("*", "/{tail:.*}", destination)
        async with TestServer(target_app) as target:
            async def redirect(request):
                raise web.HTTPFound(str(target.make_url("/leaked")))
            async def capabilities(request):
                return web.json_response({"protocolVersion": 1, "audio": example.AUDIO})
            async def create(request):
                return web.json_response({"sessionId": "s", "streamPath": "/v1/sessions/s/stream",
                                          "ticket": "fictional-ticket", "ticketExpiresInMs": 30000})
            for phase in ("http", "ws"):
                app = web.Application()
                app.router.add_get("/v1/capabilities", redirect if phase == "http" else capabilities)
                app.router.add_post("/v1/sessions", create)
                app.router.add_get("/v1/sessions/s/stream", redirect)
                app.router.add_delete("/v1/sessions/s", destination)
                async def chunks():
                    yield bytes(640)
                async with TestServer(app) as server:
                    async with example.PortalClient(str(server.make_url("/")), "fictional") as client:
                        with self.assertRaisesRegex(example.PortalError, "REDIRECT_REJECTED"):
                            await client.transcribe(chunks())
            self.assertNotIn("/leaked", visited)

    async def test_disconnect_is_not_success_and_releases_session(self):
        deleted = []
        async def capabilities(request):
            return web.json_response({"protocolVersion": 1, "audio": example.AUDIO})
        async def create(request):
            return web.json_response({"sessionId": "s", "streamPath": "/v1/sessions/s/stream",
                                      "ticket": "fictional", "ticketExpiresInMs": 30000})
        async def stream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "session.ready", "sessionId": "s", "seq": 1,
                                "audio": example.AUDIO, "finalizeTimeoutMs": 1000})
            await ws.close()
            return ws
        async def delete(request):
            deleted.append("s")
            return web.json_response({"ok": True})
        async def chunks():
            await asyncio.Future()
            yield bytes(640)
        app = web.Application()
        app.router.add_get("/v1/capabilities", capabilities)
        app.router.add_post("/v1/sessions", create)
        app.router.add_get("/v1/sessions/s/stream", stream)
        app.router.add_delete("/v1/sessions/s", delete)
        async with TestServer(app) as server:
            async with example.PortalClient(str(server.make_url("/")), "fictional") as client:
                with self.assertRaisesRegex(example.PortalError, "CONNECTION_CLOSED_WITHOUT_TERMINAL"):
                    await client.transcribe(chunks())
        self.assertEqual(deleted, ["s"])


class LedgerTests(unittest.TestCase):
    def test_changed_final_gaps_and_unfinalized_preview_are_rejected(self):
        for fault in ("changed", "gap", "pending"):
            ledger = example.Ledger("session")
            def event(kind, seq, **fields):
                return {"type": kind, "sessionId": "session", "seq": seq, **fields}
            ledger.accept(event("session.ready", 1, audio=example.AUDIO, finalizeTimeoutMs=2000))
            ledger.accept(event("transcript.partial" if fault == "pending" else "transcript.final",
                                2, utteranceId="u", revision=1, text="hello"))
            with self.assertRaises(example.PortalError):
                if fault == "changed":
                    ledger.accept(event("transcript.final", 3, utteranceId="u", revision=2, text="changed"))
                else:
                    ledger.accept(event("session.finished", 4 if fault == "gap" else 3, finalCount=1))
            self.assertFalse(ledger.terminal, "Malformed success must still trigger session cleanup")

    def test_origin_rejects_credentials_and_business_paths(self):
        for origin in ("https://user:secret@example.org", "https://example.org/admin", "file:///tmp"):
            with self.assertRaises(example.PortalError):
                example.PortalClient(origin, "fictional")
