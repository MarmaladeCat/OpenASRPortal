import asyncio
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from openasrportal.api.server import Portal
from openasrportal.storage.store import Store

PASSWORD = "Portal test password 2026!"


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        results = Path(__file__).resolve().parents[1] / "test-results"
        results.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="db-auth-", dir=results)
        self.store = Store(self.temporary.name)
        self.portal = Portal(self.store)
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temporary.cleanup()

    async def request(self, method, path, body=None, token=None, headers=None):
        headers = {**(headers or {}), **({"Authorization": "Bearer " + token} if token else {})}
        async with self.client.request(
            method, self.server.make_url(path), json=body, headers=headers, allow_redirects=False
        ) as response:
            return response.status, await response.json()

    async def setup(self, password=PASSWORD, code=None):
        _, status = await self.request("GET", "/v1/admin/auth/status")
        return await self.request(
            "POST",
            "/v1/admin/auth/setup",
            {
                "password": password,
                "confirmPassword": password,
                "setupChallenge": status["setupChallenge"],
                "pairingCode": code,
            },
        )

    async def test_first_password_is_hashed_in_database_and_sessions_are_separate(self):
        async with self.client.get(
            self.server.make_url("/admin"), allow_redirects=False
        ) as response:
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers["Location"], "/admin/setup")
        code, session = await self.setup()
        self.assertEqual(code, 201)
        token = session["token"]
        self.assertNotIn(PASSWORD.encode(), self.store.path.read_bytes())
        self.assertNotIn(token.encode(), self.store.path.read_bytes())
        with self.store.connection() as db:
            encoded = db.execute("SELECT password_hash FROM admin_credentials").fetchone()[0]
        self.assertTrue(encoded.startswith("scrypt$16384$8$1$"))
        self.assertEqual((await self.request("GET", "/v1/admin/contract", token=token))[0], 200)
        self.assertEqual((await self.request("GET", "/v1/admin/contract", token=PASSWORD))[0], 401)
        self.assertEqual((await self.request("GET", "/v1/profiles", token=token))[0], 401)
        self.assertEqual(self.store.asr_keys(), [])
        restarted = Store(self.temporary.name)
        self.assertTrue(restarted.auth.initialized())
        self.assertTrue(restarted.auth.authorized(token))
        login = restarted.auth.login(PASSWORD, "test-restart")
        self.assertTrue(restarted.auth.authorized(login["token"]))

    async def test_setup_is_once_only_and_concurrent_requests_cannot_replace_owner(self):
        first = (await self.request("GET", "/v1/admin/auth/status"))[1]["setupChallenge"]
        second = (await self.request("GET", "/v1/admin/auth/status"))[1]["setupChallenge"]
        responses = await asyncio.gather(
            *[
                self.request(
                    "POST",
                    "/v1/admin/auth/setup",
                    {
                        "password": password,
                        "confirmPassword": password,
                        "setupChallenge": challenge,
                    },
                )
                for password, challenge in ((PASSWORD, first), (PASSWORD + " second", second))
            ]
        )
        self.assertEqual(sorted(code for code, _ in responses), [201, 409])
        code, _ = await self.request(
            "POST", "/v1/admin/auth/setup", {"password": PASSWORD + " attack"}
        )
        self.assertEqual(code, 409)

    async def test_setup_rejects_weak_password_missing_challenge_csrf_and_rebinding(self):
        code, _ = await self.request(
            "POST", "/v1/admin/auth/setup", {"password": PASSWORD, "confirmPassword": PASSWORD}
        )
        self.assertEqual(code, 403)
        self.assertEqual((await self.setup("short"))[0], 400)
        self.assertFalse(self.store.auth.initialized())
        self.assertEqual(
            (
                await self.request(
                    "GET", "/v1/admin/auth/status", headers={"Origin": "https://evil.example"}
                )
            )[0],
            403,
        )
        self.assertEqual(
            (await self.request("GET", "/v1/admin/auth/status", headers={"Host": "evil.example"}))[
                0
            ],
            403,
        )
        self.assertFalse(self.store.auth.initialized())

    async def test_expiry_logout_password_recovery_and_rate_limits(self):
        _, session = await self.setup()
        token = session["token"]
        self.assertEqual((await self.request("POST", "/v1/admin/auth/logout", {}, token))[0], 200)
        self.assertFalse(self.store.auth.authorized(token))
        _, session = await self.request("POST", "/v1/admin/auth/login", {"password": PASSWORD})
        token = session["token"]
        with self.store.connection() as db:
            db.execute(
                "UPDATE admin_sessions SET expires_at=? WHERE digest=?",
                (time.time() - 1, hashlib.sha256(token.encode()).hexdigest()),
            )
        self.assertEqual((await self.request("GET", "/v1/admin/contract", token=token))[0], 401)
        session = self.store.auth.issue_session()
        self.store.auth.set_password(PASSWORD + " reset")
        self.assertFalse(self.store.auth.authorized(session["token"]))
        for _ in range(9):
            code, _ = await self.request("POST", "/v1/admin/auth/login", {"password": "wrong"})
        self.assertEqual(code, 401)
        self.assertEqual(
            (await self.request("POST", "/v1/admin/auth/login", {"password": "wrong"}))[0], 429
        )

    async def test_local_input_requires_admin_consent_and_only_its_private_claim_can_receive_key(
        self,
    ):
        _, pairing = await self.request("POST", "/v1/local-input/pairings", {"clientId": "a" * 32})
        claim = "/v1/local-input/pairings/" + pairing["id"] + "/claim"
        code, pending = await self.request("POST", claim, {"claimToken": pairing["claimToken"]})
        self.assertEqual((code, pending["state"]), (200, "pending"))
        self.assertEqual(self.store.asr_keys(), [])
        self.assertEqual((await self.request("POST", claim, {"claimToken": "bad"}))[0], 401)
        _, session = await self.setup(code=pairing["userCode"])
        self.assertTrue(session["localInputApproved"])
        _, granted = await self.request("POST", claim, {"claimToken": pairing["claimToken"]})
        self.assertEqual(granted["title"], "local-input")
        key = granted["key"]
        self.assertEqual((await self.request("GET", "/v1/profiles", token=key))[0], 200)
        self.assertEqual((await self.request("GET", "/v1/admin/contract", token=key))[0], 401)
        self.assertNotIn(key, json.dumps(self.store.asr_keys()))
        self.assertNotIn(key.encode(), self.store.path.read_bytes())
        self.assertEqual(
            (await self.request("POST", claim, {"claimToken": pairing["claimToken"]}))[1]["key"],
            key,
        )
        await self.request(
            "POST", claim.replace("/claim", "/ack"), {"claimToken": pairing["claimToken"]}
        )
        self.assertEqual(
            (await self.request("POST", claim, {"claimToken": pairing["claimToken"]}))[0], 401
        )

    async def test_pairing_is_idempotent_approval_and_revocation_are_not_bypassed(self):
        _, session = await self.setup()
        token = session["token"]
        for _ in range(2):
            _, pairing = await self.request(
                "POST", "/v1/local-input/pairings", {"clientId": "b" * 32}
            )
            route = "/v1/admin/local-input-pairings"
            result = await self.request("POST", route, {"code": pairing["userCode"]}, token)
            self.assertEqual(result[0], 200)
            await self.request("POST", route, {"code": pairing["userCode"]}, token)
        self.assertEqual(len(self.store.asr_keys()), 1)
        identity = self.store.asr_keys()[0]["id"]
        await self.request("DELETE", "/v1/admin/asr-keys/" + identity, token=token)
        claim = "/v1/local-input/pairings/" + pairing["id"] + "/claim"
        self.assertEqual(
            (await self.request("POST", claim, {"claimToken": pairing["claimToken"]}))[0], 403
        )
        self.assertEqual(len(self.store.asr_keys()), 1)

    async def test_web_pages_cannot_claim_local_keys_and_legacy_db_keys_are_preserved(self):
        for headers in (
            {"Origin": str(self.server.make_url(""))},
            {"Origin": "null"},
            {"Host": "evil.example"},
        ):
            self.assertEqual(
                (
                    await self.request(
                        "POST", "/v1/local-input/pairings", {"clientId": "c" * 32}, headers=headers
                    )
                )[0],
                403,
            )
        self.store.bootstrap_key("legacy-existing-key")
        Portal(Store(self.temporary.name))
        self.assertIsNotNone(self.store.authorize_asr("legacy-existing-key"))
        self.assertFalse(self.store.auth.initialized())

    async def test_logout_and_password_recovery_invalidate_unredeemed_browser_tickets(self):
        await self.setup()
        for recover in (False, True):
            token = self.store.auth.issue_session()["token"]
            _, ticket = await self.request("POST", "/v1/admin/ui-tickets", {}, token=token)
            if recover:
                self.store.auth.set_password(PASSWORD + " recovered")
            else:
                await self.request("POST", "/v1/admin/auth/logout", {}, token=token)
            self.assertEqual(
                (await self.request("POST", "/v1/admin/ui-session", {"ticket": ticket["ticket"]}))[
                    0
                ],
                401,
            )


if __name__ == "__main__":
    unittest.main()
