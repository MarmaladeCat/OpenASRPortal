import json
import os
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from support_auth import fixture_token
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.storage.store import Store


class AsrKeyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path(__file__).resolve().parents[1] / "test-results"
        cache.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="asr-keys-", dir=cache)
        self.store = Store(self.temporary.name)
        self.store.save("local", "Synthetic", "openlocalasr", {"apiKey": "fake-upstream"})
        self.portal = Portal(self.store, "legacy-access", "administrator", factory=FakeProvider)
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temporary.cleanup()

    async def request(self, method, route, key="administrator", body=None):
        key = fixture_token(self.portal, key)
        async with self.client.request(
            method,
            self.server.make_url(route),
            json=body,
            headers={"Authorization": "Bearer " + key},
        ) as response:
            return response.status, await response.json()

    async def create_key(self, title):
        code, result = await self.request("POST", "/v1/admin/asr-keys", body={"title": title})
        self.assertEqual(code, 201)
        return result

    async def test_management_and_recognition_permissions_never_overlap(self):
        first, second = await self.create_key("Input"), await self.create_key("Drafts")
        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual((await self.request("GET", "/v1/profiles"))[0], 401)
        for key in (first["key"], second["key"]):
            self.assertEqual((await self.request("GET", "/v1/profiles", key))[0], 200)
            self.assertEqual((await self.request("GET", "/v1/admin/asr-keys", key))[0], 401)
            self.assertEqual(
                (await self.request("POST", "/v1/admin/asr-keys", key, {"title": "bad"}))[0], 401
            )
        _, listing = await self.request("GET", "/v1/admin/asr-keys")
        self.assertNotIn(first["key"], json.dumps(listing))
        self.assertNotIn(second["key"], self.store.path.read_bytes().decode(errors="ignore"))
        self.assertIsNotNone(Store(self.temporary.name).authorize_asr(first["key"]))

    async def test_sessions_are_owned_by_individual_keys_and_revocation_is_persistent(self):
        first, second = await self.create_key("First"), await self.create_key("Second")
        _, one = await self.request("POST", "/v1/sessions", first["key"], {"profileId": "local"})
        _, two = await self.request("POST", "/v1/sessions", second["key"], {"profileId": "local"})
        self.assertEqual(
            (await self.request("DELETE", "/v1/sessions/" + one["sessionId"], second["key"]))[0],
            403,
        )
        self.assertEqual(
            (await self.request("DELETE", "/v1/admin/asr-keys/" + first["id"]))[0], 200
        )
        self.assertNotIn(one["sessionId"], self.portal.sessions)
        self.assertIn(two["sessionId"], self.portal.sessions)
        self.assertEqual((await self.request("GET", "/v1/profiles", first["key"]))[0], 401)
        self.assertEqual((await self.request("GET", "/v1/profiles", second["key"]))[0], 200)
        restarted = Portal(
            Store(self.temporary.name), "legacy-access", "administrator", factory=FakeProvider
        )
        self.assertIsNone(restarted.store.authorize_asr(first["key"]))
        legacy = next(key for key in self.store.asr_keys() if key["id"].startswith("bootstrap-"))
        await self.request("DELETE", "/v1/admin/asr-keys/" + legacy["id"])
        Portal(Store(self.temporary.name), "legacy-access", "administrator")
        self.assertIsNone(self.store.authorize_asr("legacy-access"))

    async def test_revoking_an_active_key_cancels_its_stream_only(self):
        first, second = await self.create_key("First"), await self.create_key("Second")
        _, one = await self.request("POST", "/v1/sessions", first["key"], {"profileId": "local"})
        _, two = await self.request("POST", "/v1/sessions", second["key"], {"profileId": "local"})
        socket = await self.client.ws_connect(
            self.server.make_url(one["streamPath"] + "?ticket=" + one["ticket"])
        )
        await socket.receive_json()
        await socket.receive_json()
        await self.request("DELETE", "/v1/admin/asr-keys/" + first["id"])
        self.assertEqual((await socket.receive_json())["type"], "session.cancelled")
        self.assertIn(two["sessionId"], self.portal.sessions)
        await socket.close()

    async def test_admin_password_cannot_reuse_asr_key_and_admin_setup_issues_no_asr_key(self):
        isolated = Store(Path(self.temporary.name) / "admin-only")
        isolated.bootstrap_key("same-password-key")
        with self.assertRaises(ValueError):
            isolated.auth.setup("same-password-key")
        isolated = Store(Path(self.temporary.name) / "fresh-admin-only")
        isolated.auth.setup("only-admin-password")
        self.assertEqual(isolated.asr_keys(), [])

    async def test_reveal_is_admin_only_encrypted_and_survives_restart(self):
        key = await self.create_key("Client")
        route = "/v1/admin/asr-keys/" + key["id"] + "/secret"
        self.assertEqual((await self.request("GET", route, key["key"]))[0], 401)
        code, value = await self.request("GET", route)
        self.assertEqual((code, value["key"]), (200, key["key"]))
        self.assertEqual(Store(self.temporary.name).reveal_asr_key(key["id"]), key["key"])
        self.assertNotIn(key["key"], self.store.path.read_bytes().decode(errors="ignore"))
        if os.name != "nt":  # Windows reports DOS attributes, not POSIX ACL permissions.
            self.assertEqual(self.store.vault.path.stat().st_mode & 0o777, 0o600)
        await self.request("DELETE", "/v1/admin/asr-keys/" + key["id"])
        self.assertEqual((await self.request("GET", route))[0], 400)

    async def test_old_hash_only_key_can_only_be_recovered_with_matching_original(self):
        first, second = await self.create_key("First"), await self.create_key("Second")
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE asr_keys SET encrypted_secret=NULL WHERE id=?", (first["id"],)
            )
        reveal = "/v1/admin/asr-keys/" + first["id"] + "/secret"
        recover = "/v1/admin/asr-keys/" + first["id"] + "/recover"
        self.assertEqual((await self.request("GET", reveal))[0], 409)
        self.assertEqual((await self.request("POST", recover, body={"key": second["key"]}))[0], 400)
        self.assertFalse(self.store.asr_key(first["id"])["canReveal"])
        self.assertEqual((await self.request("POST", recover, body={"key": first["key"]}))[0], 200)
        self.assertEqual((await self.request("GET", reveal))[1]["key"], first["key"])

    async def test_lost_vault_does_not_silently_rotate_or_expose_keys(self):
        key = await self.create_key("Client")
        self.store.vault.path.unlink()
        route = "/v1/admin/asr-keys/" + key["id"] + "/secret"
        self.assertEqual((await self.request("GET", route))[0], 409)
        self.assertEqual(
            (await self.request("POST", "/v1/admin/asr-keys", body={"title": "Next"}))[0], 409
        )
        self.assertFalse(self.store.vault.path.exists())
