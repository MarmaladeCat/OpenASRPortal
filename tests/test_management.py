import hashlib
import json
import tempfile
import time
import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from support_auth import fixture_token
from support_auth import portal_for_tests as Portal

from openasrportal.storage.store import Store


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.portal = Portal(self.store, "client-key", "private-administrator-credential")
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temporary.cleanup()

    async def request(self, method, route, body=None, key="private-administrator-credential"):
        key = fixture_token(self.portal, key)
        async with self.client.request(
            method,
            self.server.make_url(route),
            json=body,
            headers={"Authorization": "Bearer " + key},
        ) as response:
            return response.status, await response.json()

    async def test_contract_and_complete_crud_are_shared_and_redacted(self):
        self.assertEqual(
            (await self.request("GET", "/v1/admin/contract", key="client-key"))[0], 401
        )
        code, descriptor = await self.request("GET", "/v1/admin/contract")
        self.assertEqual(
            (code, descriptor["protocol"], descriptor["version"]),
            (200, "OpenASRPortal.Management", 1),
        )
        self.assertEqual(
            {provider["id"] for provider in descriptor["providers"]},
            {"openlocalasr", "doubao_realtime", "bailian_qwen_asr", "boson_realtime", "soniox_realtime"},
        )
        body = {
            "id": "local",
            "title": "我的识别",
            "provider": "openlocalasr",
            "configuration": {"apiKey": "upstream-secret"},
        }
        self.assertEqual((await self.request("POST", "/v1/admin/profiles", body))[0], 201)
        self.assertEqual((await self.request("POST", "/v1/admin/profiles", body))[0], 409)
        _, listing = await self.request("GET", "/v1/admin/profiles")
        self.assertEqual(listing["defaultProfileId"], "local")
        self.assertNotIn("upstream-secret", json.dumps(listing))
        self.assertEqual(
            (
                await self.request(
                    "PATCH",
                    "/v1/admin/profiles/local",
                    {"title": "新名称", "configuration": {"model": "new-model"}},
                )
            )[0],
            200,
        )
        self.assertEqual(self.store.get("local")["configuration"]["apiKey"], "upstream-secret")
        self.assertEqual(
            (await self.request("GET", "/v1/admin/profiles/local"))[1]["title"], "新名称"
        )
        self.assertEqual((await self.request("DELETE", "/v1/admin/profiles/local"))[0], 200)
        self.assertEqual((await self.request("GET", "/v1/admin/profiles"))[1]["profiles"], [])
        self.assertEqual((await self.request("PATCH", "/v1/admin/profiles/missing", body))[0], 404)

    async def test_default_selection_and_active_snapshot_survive_profile_changes(self):
        for profile_id in ("first", "second"):
            self.store.save(profile_id, profile_id, "openlocalasr", {"apiKey": "key"})
        await self.request("PATCH", "/v1/admin/settings", {"defaultProfileId": "second"})
        self.assertEqual(
            (await self.request("GET", "/v1/profiles", key="client-key"))[1]["defaultProfileId"],
            "second",
        )
        _, session = await self.request(
            "POST", "/v1/sessions", {"profileId": "second"}, key="client-key"
        )
        await self.request("DELETE", "/v1/admin/profiles/second")
        self.assertEqual(self.portal.sessions[session["sessionId"]].profile["id"], "second")
        self.assertEqual(self.store.settings()["defaultProfileId"], "first")
        self.assertEqual(
            (await self.request("PATCH", "/v1/admin/settings", {"defaultProfileId": "missing"}))[0],
            400,
        )

    async def test_proxy_admin_only_and_per_profile_selection(self):
        payload = {"proxy": {"url": "http://proxy.example:8080", "username": "test-user",
                             "password": "fictional-proxy-secret"}}
        self.assertEqual((await self.request("PATCH", "/v1/admin/settings", payload,
                                            key="client-key"))[0], 401)
        code, settings = await self.request("PATCH", "/v1/admin/settings", payload)
        self.assertEqual(code, 200)
        self.assertEqual(settings["proxy"], {"url": payload["proxy"]["url"], "hasCredentials": True})
        self.assertNotIn("proxy", (await self.request("GET", "/v1/profiles", key="client-key"))[1])
        for use_proxy in (True, False):
            self.store.save("local", "Local", "openlocalasr", {"apiKey": "key", "useProxy": use_proxy})
            provider = self.portal.factory(self.store.get("local"))
            self.assertEqual(provider.config["useProxy"], use_proxy)
            self.assertEqual(provider.config["_proxy"], payload["proxy"] if use_proxy else None)
        for route in ("/v1/admin/settings", "/v1/admin/profiles", "/v1/admin/profiles/local"):
            self.assertNotIn("fictional-proxy-secret", json.dumps((await self.request("GET", route))[1]))

    async def test_same_endpoint_profiles_keep_independent_keys_and_sessions(self):
        for identity, key in (("doubao-1", "key-1"), ("doubao-2", "key-2")):
            body = {
                "id": identity,
                "title": identity,
                "provider": "doubao_realtime",
                "configuration": {},
            }
            # Neither an omitted nor an empty key can borrow another profile's key.
            for configuration in ({}, {"apiKey": ""}):
                body["configuration"] = configuration
                self.assertEqual((await self.request("POST", "/v1/admin/profiles", body))[0], 400)
                self.assertIsNone(self.store.get(identity))
            body["configuration"] = {"apiKey": key}
            self.assertEqual((await self.request("POST", "/v1/admin/profiles", body))[0], 201)
            _, session = await self.request(
                "POST", "/v1/sessions", {"profileId": identity}, key="client-key"
            )
            self.assertEqual(
                self.portal.sessions[session["sessionId"]].profile["configuration"]["apiKey"],
                key,
            )

        first, second = (self.store.get(identity) for identity in ("doubao-1", "doubao-2"))
        self.assertEqual(first["configuration"]["endpoint"], second["configuration"]["endpoint"])
        for route, key in (
            ("/v1/admin/profiles", "private-administrator-credential"),
            ("/v1/profiles", "client-key"),
        ):
            _, listing = await self.request("GET", route, key=key)
            self.assertEqual(len(listing["profiles"]), 2)
            self.assertNotIn("key-1", json.dumps(listing))
            self.assertNotIn("key-2", json.dumps(listing))

        self.assertEqual(
            (await self.request("PATCH", "/v1/admin/profiles/doubao-2", {"title": "备用豆包"}))[0],
            200,
        )
        self.assertEqual(self.store.get("doubao-2")["configuration"]["apiKey"], "key-2")
        self.assertEqual(
            (
                await self.request(
                    "PATCH",
                    "/v1/admin/profiles/doubao-1",
                    {"configuration": {"apiKey": "key-1-new"}},
                )
            )[0],
            200,
        )
        self.assertEqual(self.store.get("doubao-1")["configuration"]["apiKey"], "key-1-new")
        self.assertEqual(self.store.get("doubao-2")["configuration"]["apiKey"], "key-2")
        self.assertEqual((await self.request("DELETE", "/v1/admin/profiles/doubao-1"))[0], 200)
        self.assertEqual(self.store.get("doubao-2")["configuration"]["apiKey"], "key-2")

    async def test_management_page_ticket_is_one_use_and_admin_only(self):
        self.assertEqual(
            (await self.request("POST", "/v1/admin/ui-tickets", key="client-key"))[0], 401
        )
        _, value = await self.request("POST", "/v1/admin/ui-tickets")
        _, login = await self.request(
            "POST", "/v1/admin/ui-session", {"ticket": value["ticket"]}, key=""
        )
        token = login["token"]
        self.assertEqual((await self.request("GET", "/v1/admin/contract", key=token))[0], 200)
        self.assertEqual((await self.request("GET", "/v1/profiles", key=token))[0], 401)
        self.assertEqual(
            (
                await self.request(
                    "POST", "/v1/admin/ui-session", {"ticket": value["ticket"]}, key=""
                )
            )[0],
            401,
        )
        with self.store.connection() as db:
            db.execute(
                "UPDATE admin_sessions SET expires_at=? WHERE digest=?",
                (time.time() - 1, hashlib.sha256(token.encode()).hexdigest()),
            )
        self.assertEqual((await self.request("GET", "/v1/admin/contract", key=token))[0], 401)

    async def test_portable_web_assets_do_not_expose_credentials(self):
        for route in (
            "/admin",
            "/admin/app.js",
            "/admin/style.css",
            "/admin/personal-hotwords.mjs",
        ):
            async with self.client.get(self.server.make_url(route)) as response:
                self.assertEqual(response.status, 200)
                self.assertNotIn("private-administrator-credential", await response.text())
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        async with self.client.get(self.server.make_url("/admin/private.db")) as response:
            self.assertEqual(response.status, 404)

    async def test_non_object_management_requests_return_protocol_errors(self):
        for route in ("/v1/admin/settings", "/v1/admin/ui-session"):
            method = "PATCH" if route.endswith("settings") else "POST"
            code, value = await self.request(method, route, [])
            self.assertEqual(code, 400)
            self.assertEqual(value["error"]["code"], "INVALID_REQUEST")
