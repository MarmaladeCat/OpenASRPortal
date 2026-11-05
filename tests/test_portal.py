"""公开 API 回归：独立认证、凭据脱敏、会话隔离、定稿与取消。"""

import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError, web
from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests as Portal

from openasrportal.domain.asr_protocol import text_event
from openasrportal.storage.store import Store


class FakeProvider:
    text_processing = "native"
    finish_timeout = 1

    def __init__(self, profile):
        self.profile = profile
        self.queue = asyncio.Queue()
        self.closed = False

    async def open(self):
        await self.queue.put(([text_event("partial_result", "错误预览", 0, 100)], False))

    async def send_audio(self, data, last=False):
        if last and self.profile["configuration"].get("model") != "never_finish":
            await self.queue.put(([text_event("final_result", "最终文本。", 0, 500)], True))

    async def receive(self):
        return await self.queue.get()

    async def close(self):
        self.closed = True


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.providers = []

        def factory(profile):
            provider = FakeProvider(profile)
            self.providers.append(provider)
            return provider

        self.store = Store(self.temp.name)
        self.store.save("local", "本地配置", "openlocalasr", {"apiKey": "upstream-secret"})
        self.portal = Portal(self.store, "client-key", "admin-key", factory=factory)
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession(headers={"Authorization": "Bearer client-key"})

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    def url(self, path):
        return self.server.make_url(path)

    async def create(self, **fields):
        async with self.client.post(
            self.url("/v1/sessions"), json={"profileId": "local", **fields}
        ) as response:
            self.assertEqual(response.status, 201)
            return await response.json()

    async def ws(self, session):
        return await self.client.ws_connect(
            self.url(session["streamPath"] + "?ticket=" + session["ticket"])
        )

    async def test_authentication_and_profile_redaction(self):
        async with self.client.get(self.url("/v1/profiles")) as response:
            listing = await response.json()
            self.assertNotIn("upstream-secret", json.dumps(listing))
            self.assertTrue(listing["profiles"][0]["configuration"]["hasApiKey"])
        async with self.client.get(self.url("/v1/admin/profiles/local")) as response:
            self.assertEqual(response.status, 401)
        async with self.client.get(
            self.url("/v1/profiles"), headers={"Authorization": "Bearer wrong"}
        ) as response:
            self.assertEqual(response.status, 401)
        async with self.client.patch(
            self.url("/v1/admin/profiles/local"),
            headers={"Authorization": "Bearer " + self.portal.test_admin_token},
            json={"configuration": {"model": "other"}},
        ) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.store.get("local")["configuration"]["apiKey"], "upstream-secret")
        self.assertEqual(Store(self.temp.name).get("local")["configuration"]["model"], "other")

    async def test_default_resolution_explicit_override_and_session_snapshot(self):
        self.store.save("cloud", "云端配置", "doubao_realtime", {"apiKey": "cloud-secret"})
        self.store.set_default("cloud")
        for body in ({}, {"profileId": ""}, {"profileId": None}, {"profileId": "local"}):
            async with self.client.post(self.url("/v1/sessions"), json=body) as response:
                self.assertEqual(response.status, 201)
                descriptor = await response.json()
            selected = self.portal.sessions[descriptor["sessionId"]].profile["id"]
            self.assertEqual(selected, "local" if body.get("profileId") == "local" else "cloud")
        self.store.set_default("local")
        self.assertEqual(self.portal.sessions[descriptor["sessionId"]].profile["id"], "local")
        self.assertEqual(next(iter(self.portal.sessions.values())).profile["id"], "cloud")
        async with self.client.post(self.url("/v1/sessions"), json={}) as response:
            self.assertEqual(response.status, 201)
            latest = await response.json()
        self.assertEqual(self.portal.sessions[latest["sessionId"]].profile["id"], "local")

    async def test_missing_default_and_invalid_override_do_not_silently_reroute(self):
        self.store.set_default("")
        for body, status, code in (
            ({}, 404, "PROFILE_NOT_FOUND"),
            ({"profileId": "missing"}, 404, "PROFILE_NOT_FOUND"),
            ({"profileId": 42}, 400, "INVALID_PROFILE"),
            ({"profileId": " "}, 400, "INVALID_PROFILE"),
        ):
            async with self.client.post(self.url("/v1/sessions"), json=body) as response:
                self.assertEqual(response.status, status)
                self.assertEqual((await response.json())["error"]["code"], code)
        self.assertFalse(self.portal.sessions)
        await self.create()  # An explicit profile works even without a default.

    async def test_stream_has_stable_ids_and_complete_finalization(self):
        session = await self.create()
        socket = await self.ws(session)
        ready = await socket.receive_json()
        partial = await socket.receive_json()
        self.assertEqual(ready["type"], "session.ready")
        await socket.send_bytes(bytes(6400))
        await socket.send_json({"type": "audio.end"})
        final = await socket.receive_json()
        done = await socket.receive_json()
        self.assertEqual(partial["utteranceId"], final["utteranceId"])
        self.assertGreater(final["revision"], partial["revision"])
        self.assertEqual(final["text"], "最终文本。")
        self.assertEqual((done["type"], done["finalCount"]), ("session.finished", 1))
        self.assertEqual([ready["seq"], partial["seq"], final["seq"], done["seq"]], [1, 2, 3, 4])
        await socket.close()
        await asyncio.sleep(0.01)
        self.assertTrue(self.providers[0].closed)

    async def test_cancel_does_not_close_other_session_or_share_snapshot(self):
        first = await self.create()
        self.store.save("local", "新配置", "openlocalasr", {"model": "new-model"})
        second = await self.create()
        self.assertNotEqual(
            self.portal.sessions[first["sessionId"]].profile["configuration"]["model"],
            self.portal.sessions[second["sessionId"]].profile["configuration"]["model"],
        )
        one, two = await self.ws(first), await self.ws(second)
        for socket in (one, two):
            await socket.receive_json()
            await socket.receive_json()
        await one.send_json({"type": "session.cancel"})
        self.assertEqual((await one.receive_json())["type"], "session.cancelled")
        await two.send_json({"type": "audio.end"})
        self.assertEqual((await two.receive_json())["type"], "transcript.final")
        self.assertEqual((await two.receive_json())["type"], "session.finished")
        await one.close()
        await two.close()

    async def test_idempotency_expiration_and_ticket_single_use(self):
        first = await self.create(clientRequestId="unique")
        repeat = await self.create(clientRequestId="unique")
        self.assertEqual(first["sessionId"], repeat["sessionId"])
        self.portal.sessions[first["sessionId"]].expires = 0
        async with self.client.get(
            self.url(first["streamPath"] + "?ticket=" + first["ticket"])
        ) as response:
            self.assertEqual(response.status, 401)
        session = await self.create()
        socket = await self.ws(session)
        await socket.receive_json()
        async with self.client.get(
            self.url(session["streamPath"] + "?ticket=" + session["ticket"])
        ) as response:
            self.assertEqual(response.status, 401)
        await socket.close()

    async def test_invalid_audio_and_finalize_timeout_are_not_success(self):
        session = await self.create()
        socket = await self.ws(session)
        await socket.receive_json()
        await socket.receive_json()
        await socket.send_bytes(b"x")
        error = await socket.receive_json()
        self.assertEqual((error["type"], error["code"]), ("session.error", "UNSUPPORTED_AUDIO"))
        self.assertEqual((await socket.receive()).type, WSMsgType.CLOSE)
        await socket.close()

    async def test_capacity_is_released_by_unconnected_cancel(self):
        self.portal.max_sessions = 1
        session = await self.create()
        async with self.client.post(
            self.url("/v1/sessions"), json={"profileId": "local"}
        ) as response:
            self.assertEqual(response.status, 429)
        async with self.client.delete(self.url("/v1/sessions/" + session["sessionId"])) as response:
            self.assertEqual(response.status, 200)
        await self.create()

    async def test_finalize_timeout_emits_error_and_releases_session(self):
        self.store.save("local", "不定稿", "openlocalasr", {"model": "never_finish"})
        session = await self.create()
        socket = await self.ws(session)
        await socket.receive_json()
        await socket.receive_json()
        await socket.send_json({"type": "audio.end"})
        event = await socket.receive_json()
        self.assertEqual((event["type"], event["code"]), ("session.error", "FINALIZATION_TIMEOUT"))
        await socket.close()
        await asyncio.sleep(0.01)
        self.assertNotIn(session["sessionId"], self.portal.sessions)
        self.assertTrue(self.providers[0].closed)

    async def test_failed_websocket_upgrade_releases_capacity_and_finishes_usage(self):
        self.portal.max_sessions = 1
        session = await self.create()
        with patch.object(
            web.WebSocketResponse, "prepare", AsyncMock(side_effect=ConnectionResetError("lost"))
        ):
            with self.assertRaises(WSServerHandshakeError):
                await self.ws(session)
        self.assertNotIn(session["sessionId"], self.portal.sessions)
        self.assertFalse(self.providers)
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM usage_sessions WHERE id=?", (session["sessionId"],)
            ).fetchone()
            self.assertEqual(row["state"], "failed")
        await self.create()

    async def test_failed_session_persistence_does_not_reserve_capacity(self):
        with patch.object(self.store.usage, "new_session", side_effect=RuntimeError("disk full")):
            async with self.client.post(
                self.url("/v1/sessions"), json={"profileId": "local"}
            ) as response:
                self.assertEqual(response.status, 500)
        self.assertFalse(self.portal.sessions)
        await self.create()

    async def test_cancel_during_provider_open_does_not_start_metered_call(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = FakeProvider.open

        async def delayed(provider):
            entered.set()
            await release.wait()
            await original(provider)

        with (
            patch.object(FakeProvider, "open", delayed),
            patch.object(
                self.store.usage, "begin_call", wraps=self.store.usage.begin_call
            ) as begin,
        ):
            session = await self.create()
            socket = await self.ws(session)
            await entered.wait()
            deleting = asyncio.create_task(
                self.client.delete(self.url("/v1/sessions/" + session["sessionId"]))
            )
            self.assertEqual((await socket.receive_json())["type"], "session.cancelled")
            release.set()
            await socket.close()
            response = await deleting
            self.assertEqual(response.status, 200)
            response.release()
            for _ in range(50):
                if session["sessionId"] not in self.portal.sessions:
                    break
                await asyncio.sleep(0.01)
            begin.assert_not_called()
            self.assertNotIn(session["sessionId"], self.portal.sessions)
            self.assertTrue(self.providers[0].closed)

    async def test_unsaved_connection_test_does_not_create_or_update_profile(self):
        async with self.client.post(
            self.url("/v1/admin/profiles/unsaved/test"),
            headers={"Authorization": "Bearer " + self.portal.test_admin_token},
            json={
                "provider": "openlocalasr",
                "configuration": {"apiKey": "draft-key", "model": "draft-model"},
            },
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["ok"])
        self.assertIsNone(self.store.get("unsaved"))
        self.assertEqual(self.providers[-1].profile["configuration"]["model"], "draft-model")
        self.assertTrue(self.providers[-1].closed)


if __name__ == "__main__":
    unittest.main()
