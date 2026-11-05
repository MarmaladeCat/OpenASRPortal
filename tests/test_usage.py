"""Offline accounting/quota regressions, including real Portal WS and HTTP adapter calls."""

import asyncio
import hashlib
import json
import sqlite3
import struct
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.providers.bailian_asr import BailianProvider
from openasrportal.storage.store import Store
from openasrportal.storage.usage import UsageError, reported_tokens

ROOT = Path(__file__).resolve().parents[1]
OWNER = hashlib.sha256(b"usage-client").hexdigest()


class AccountingTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="usage-", dir=ROOT / "test-results")
        self.store = Store(self.directory.name)
        self.store.bootstrap_key("usage-client")
        self.store.save("local", "Local", "openlocalasr", {"apiKey": "fake-upstream"})
        self.key_id = self.store.asr_keys()[0]["id"]
        self.usage = self.store.usage

    def tearDown(self):
        self.directory.cleanup()

    def start(self, identity="s", profile="local"):
        self.usage.new_session(identity, OWNER, profile)
        self.usage.activate(identity)
        return identity

    def test_streaming_audio_balances_are_atomic_across_concurrent_sessions(self):
        self.usage.update_quota("key", self.key_id, {"remainingSeconds": 0.15})
        for index in range(20):
            self.start(str(index))

        def submit(identity):
            try:
                return self.usage.accept_audio(str(identity), 640)[0]
            except UsageError as error:
                self.assertEqual(error.code, "QUOTA_EXHAUSTED")
                return 0

        with ThreadPoolExecutor(max_workers=8) as executor:
            accepted = sum(executor.map(submit, range(20)))
        self.assertEqual(accepted, 4800)
        self.assertEqual(self.usage.quota("key", self.key_id)["remainingSeconds"], 0)
        self.assertEqual(self.usage.quota("key", self.key_id)["usedSeconds"], 0.15)
        self.assertEqual(self.usage.quota("profile", "local")["usedSeconds"], 0.15)

    def test_ordered_rotation_skips_disabled_and_exhausted_profiles_and_restores_default(self):
        for identity in ("second", "third"):
            self.store.save(identity, identity, "openlocalasr", {"apiKey": "fake-upstream"})
        self.usage.set_order(["third", "local", "second"])
        self.store.set_default("local")
        self.usage.update_quota("profile", "local", {"remainingSeconds": 0})
        self.assertEqual(self.store.settings()["defaultProfileId"], "second")
        self.usage.update_quota("profile", "second", {"enabled": False})
        self.assertEqual(self.store.settings()["defaultProfileId"], "third")
        self.usage.update_quota("profile", "third", {"remainingSeconds": 0})
        self.assertEqual(self.store.settings()["defaultProfileId"], "")
        self.usage.update_quota("profile", "local", {"remainingSeconds": 10})
        self.assertEqual(self.store.settings()["defaultProfileId"], "local")
        self.usage.update_quota("profile", "second", {"remainingSeconds": 10})
        self.assertFalse(self.usage.quota("profile", "second")["enabled"])

    def test_explicitly_cleared_default_is_not_overwritten_by_quota_changes(self):
        self.store.set_default("")
        self.usage.update_quota("profile", "local", {"remainingSeconds": 10})
        self.assertEqual(self.store.settings()["defaultProfileId"], "")

    def test_http_final_reservation_prevents_previews_from_spending_final_credit(self):
        self.store.save("cloud", "Cloud", "bailian_qwen_asr", {"apiKey": "fake-upstream"})
        self.usage.update_quota("profile", "cloud", {"remainingSeconds": 0.4})
        self.start(profile="cloud")
        accepted, _ = self.usage.accept_audio("s", 6400, snapshot=True)
        self.assertEqual(accepted, 6400)
        self.assertEqual(self.usage.quota("profile", "cloud")["reservedSeconds"], 0.2)
        preview = self.usage.begin_call("s", 6400, final=False, snapshot=True)
        self.assertIsNotNone(preview)
        self.usage.complete_call(preview, {"total": 5, "input": 3, "output": 2})
        self.assertIsNone(self.usage.begin_call("s", 6400, final=False, snapshot=True))
        final = self.usage.begin_call("s", 6400, final=True, snapshot=True)
        self.usage.complete_call(final, {"total": 6, "input": 4, "output": 2})
        self.usage.finish("s", "finished")
        self.assertEqual(self.usage.quota("profile", "cloud")["usedSeconds"], 0.4)
        self.assertEqual(self.usage.quota("key", self.key_id)["usedSeconds"], 0.2)
        self.assertEqual(self.usage.quota("key", self.key_id)["reportedTokens"], 11)
        self.assertFalse(self.usage.quota("profile", "cloud")["enabled"])

    def test_tokens_are_not_guessed_and_duplicate_response_cannot_double_charge(self):
        self.start()
        event = self.usage.begin_call("s", 3200, snapshot=True)
        value = {"total": 9, "input": 6, "output": 3}
        self.usage.complete_call(event, value)
        self.usage.complete_call(event, value)
        self.assertEqual(self.usage.quota("key", self.key_id)["reportedTokens"], 9)
        self.assertEqual(
            reported_tokens({"usage": {"prompt_tokens": 6, "completion_tokens": 3}}), value
        )
        self.assertIsNone(
            reported_tokens({"usage": {"seconds": 1}, "output": {"text": "some words"}})
        )
        self.assertIsNone(reported_tokens({"usage": {"total_tokens": True}}))
        self.assertEqual(
            reported_tokens({"output": {"output": {"usage": {"total_tokens": 2}}}})["total"], 2
        )

    def test_missing_token_report_blocks_token_limited_account_until_admin_changes_quota(self):
        self.store.save("cloud", "Cloud", "bailian_qwen_asr", {"apiKey": "fake-upstream"})
        self.usage.update_quota("key", self.key_id, {"remainingTokens": 100})
        self.start(profile="cloud")
        event = self.usage.begin_call("s", 3200, snapshot=True)
        with self.assertRaises(UsageError) as result:
            self.usage.complete_call(event, None)
        self.assertEqual(result.exception.code, "TOKEN_USAGE_UNAVAILABLE")
        self.assertTrue(self.usage.quota("key", self.key_id)["tokenBlocked"])
        self.assertIsNone(self.usage.quota("key", self.key_id)["tokens"])
        with self.assertRaises(UsageError):
            self.usage.check(OWNER, self.store.get("cloud"))
        self.usage.update_quota("key", self.key_id, {"remainingTokens": None})
        self.usage.check(OWNER, self.store.get("cloud"))

    def test_time_ranges_timezone_and_history_survive_profile_deletion(self):
        self.usage.clock = lambda: datetime(
            2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc
        ).timestamp()
        self.start()
        self.usage.begin_call("s")
        self.usage.accept_audio("s", 3200)
        self.usage.clock = lambda: datetime(2026, 10, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp()
        self.usage.accept_audio("s", 6400)
        self.usage.finish("s", "finished")
        begin = datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()
        end = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
        utc = self.usage.statistics(begin, end, "month", self.key_id)
        self.assertEqual(len(utc["timeline"]), 2)
        china = self.usage.statistics(begin, end, "day", timezone_name="Asia/Shanghai")
        self.assertEqual(len(china["timeline"]), 1)
        self.assertAlmostEqual(china["total"]["audioSeconds"], 0.3)
        self.assertIsNone(china["total"]["tokens"])
        self.store.delete("local")
        historical = self.usage.statistics(begin, end, profile_id="local")
        self.assertAlmostEqual(historical["total"]["upstreamAudioSeconds"], 0.3)

    def test_restart_keeps_counters_releases_holds_and_marks_interrupted_usage(self):
        self.store.save("cloud", "Cloud", "bailian_qwen_asr", {"apiKey": "fake-upstream"})
        self.usage.update_quota("key", self.key_id, {"remainingTokens": 100})
        self.start(profile="cloud")
        self.usage.accept_audio("s", 6400, snapshot=True)
        self.usage.begin_call("s", 6400, final=True, snapshot=True)
        reopened = Store(self.directory.name)
        reopened.usage.recover()
        quota = reopened.usage.quota("key", self.key_id)
        self.assertEqual(quota["usedSeconds"], 0.2)
        self.assertTrue(quota["tokenBlocked"])
        self.assertEqual(reopened.usage.quota("profile", "cloud")["reservedSeconds"], 0)
        with reopened.connection() as db:
            self.assertEqual(
                db.execute("SELECT state FROM usage_sessions WHERE id='s'").fetchone()[0],
                "interrupted",
            )

    def test_invalid_quota_patch_does_not_partly_apply_or_reset_usage(self):
        self.start()
        self.usage.accept_audio("s", 3200)
        for patch in (
            {"remainingSeconds": -1},
            {"remainingSeconds": 10**500},
            {"remainingTokens": True},
            {"remainingSeconds": 3, "remainingTokens": 1.2},
            {"enabled": "true"},
            {"unknown": 1},
        ):
            with self.assertRaises(ValueError):
                self.usage.update_quota("profile", "local", patch)
        self.assertEqual(self.usage.quota("profile", "local")["usedSeconds"], 0.1)
        self.assertIsNone(self.usage.quota("profile", "local")["remainingSeconds"])
        with self.assertRaises(ValueError):
            self.usage.update_quota("profile", "local", {"remainingTokens": 10})

    def test_invalid_combined_settings_patch_is_atomic(self):
        self.store.save("second", "Second", "openlocalasr", {"apiKey": "fake-upstream"})
        with self.assertRaises(ValueError):
            self.usage.configure_defaults(
                {"profileOrder": ["second", "local"], "defaultProfileId": "missing"}
            )
        self.assertEqual(self.store.settings()["profileOrder"], ["local", "second"])

    def test_audio_events_are_compacted_by_minute_without_losing_sample_counts(self):
        self.usage.clock = lambda: 1800000000.0
        self.start()
        for _ in range(100):
            self.usage.accept_audio("s", 2)
        with self.store.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM usage_events WHERE requests=0").fetchone()[0], 1
            )
        self.assertEqual(self.usage.quota("key", self.key_id)["usedSeconds"], 200 / 32000)
        self.usage.clock = lambda: 1800000060.0
        self.usage.accept_audio("s", 2)
        with self.store.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM usage_events WHERE requests=0").fetchone()[0], 2
            )
        self.assertEqual(self.usage.quota("key", self.key_id)["usedSeconds"], 202 / 32000)

    def test_legacy_database_migration_keeps_credentials_and_default(self):
        with tempfile.TemporaryDirectory(
            prefix="usage-legacy-", dir=ROOT / "test-results"
        ) as directory:
            db = sqlite3.connect(Path(directory) / "portal.db")
            db.execute(
                "CREATE TABLE profiles(id TEXT PRIMARY KEY,title TEXT,provider TEXT,configuration TEXT)"
            )
            db.execute(
                "INSERT INTO profiles VALUES (?,?,?,?)",
                ("old", "Legacy", "openlocalasr", json.dumps({"apiKey": "old-secret"})),
            )
            db.commit()
            db.close()
            store = Store(directory)
            self.assertEqual(store.get("old")["configuration"]["apiKey"], "old-secret")
            self.assertEqual(store.settings()["defaultProfileId"], "old")
            self.assertIsNone(store.usage.quota("profile", "old")["remainingSeconds"])


class UsageApiFixture:
    async def asyncSetUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="usage-api-", dir=ROOT / "test-results")
        self.store = Store(self.directory.name)
        self.store.save("local", "Local", "openlocalasr", {"apiKey": "fake-upstream"})
        self.providers = []

        class CapturingProvider(FakeProvider):
            def __init__(instance, profile):
                super().__init__(profile)
                instance.audio = bytearray()
                self.providers.append(instance)

            async def send_audio(instance, pcm, last=False):
                instance.audio.extend(pcm)
                await super().send_audio(pcm, last)

        self.portal = Portal(self.store, "usage-client", "admin-key", factory=CapturingProvider)
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession(headers={"Authorization": "Bearer usage-client"})
        self.admin = {"Authorization": "Bearer " + self.portal.test_admin_token}
        self.key_id = self.store.asr_keys()[0]["id"]

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.directory.cleanup()

    def url(self, path):
        return self.server.make_url(path)

    async def session(self):
        async with self.client.post(self.url("/v1/sessions"), json={}) as response:
            self.assertEqual(response.status, 201)
            descriptor = await response.json()
        return await self.client.ws_connect(
            self.url(descriptor["streamPath"] + "?ticket=" + descriptor["ticket"])
        )

    async def terminal(self, socket):
        events = []
        while True:
            event = await socket.receive_json(timeout=3)
            events.append(event)
            if event["type"] in ("session.finished", "session.error", "session.cancelled"):
                return events


class UsageApiTests(UsageApiFixture, unittest.IsolatedAsyncioTestCase):
    async def test_key_duration_limit_finalizes_only_allowed_audio_and_rejects_next_session(self):
        async with self.client.patch(
            self.url(f"/v1/admin/asr-keys/{self.key_id}/quota"),
            headers=self.admin,
            json={"remainingSeconds": 0.1},
        ) as response:
            self.assertEqual(response.status, 200)
        socket = await self.session()
        await socket.send_bytes(bytes(6400))
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["reason"], "quota_exhausted")
        self.assertEqual(len(self.providers[0].audio), 3200)
        async with self.client.post(self.url("/v1/sessions"), json={}) as response:
            self.assertEqual(response.status, 402)
        async with self.client.get(self.url("/v1/admin/usage"), headers=self.admin) as response:
            self.assertEqual((await response.json())["total"]["audioSeconds"], 0.1)
        await socket.close()

    async def test_admin_statistics_and_limits_cannot_be_modified_by_recognition_key(self):
        for method, path, body in (
            ("GET", "/v1/admin/usage", None),
            ("PATCH", f"/v1/admin/asr-keys/{self.key_id}/quota", {"remainingSeconds": 0}),
            ("PATCH", "/v1/admin/profiles/local/quota", {"enabled": False}),
        ):
            async with self.client.request(method, self.url(path), json=body) as response:
                self.assertEqual(response.status, 401)
        self.assertTrue(self.store.usage.quota("profile", "local")["enabled"])
        async with self.client.get(self.url("/v1/profiles")) as response:
            profile = (await response.json())["profiles"][0]
            self.assertNotIn("usedSeconds", profile["quota"])
            self.assertNotIn("remainingTokens", profile["quota"])

    async def test_upstream_disabled_by_quota_rotates_default_and_all_empty_returns_actionable_error(
        self,
    ):
        self.store.save("next", "Next", "openlocalasr", {"apiKey": "fake-upstream"})
        async with self.client.patch(
            self.url("/v1/admin/profiles/local/quota"),
            headers=self.admin,
            json={"remainingSeconds": 0.1},
        ) as response:
            self.assertEqual(response.status, 200)
        socket = await self.session()
        await socket.send_bytes(bytes(6400))
        await self.terminal(socket)
        self.assertEqual(self.store.settings()["defaultProfileId"], "next")
        await socket.close()
        self.store.usage.update_quota("profile", "next", {"remainingSeconds": 0})
        async with self.client.post(self.url("/v1/sessions"), json={}) as response:
            self.assertEqual(response.status, 503)
            self.assertEqual((await response.json())["error"]["code"], "NO_UPSTREAM_AVAILABLE")

    async def test_token_limited_key_cannot_bypass_metering_with_duration_only_provider(self):
        self.store.usage.update_quota("key", self.key_id, {"remainingTokens": 10})
        async with self.client.post(self.url("/v1/sessions"), json={}) as response:
            self.assertEqual(response.status, 409)
            self.assertEqual((await response.json())["error"]["code"], "TOKEN_USAGE_UNSUPPORTED")

    async def test_invalid_statistics_time_and_bucket_return_json_errors(self):
        for query in ("from=bad", "from=2&to=1", "bucket=invalid", "timezone=../../bad"):
            async with self.client.get(
                self.url("/v1/admin/usage?" + query), headers=self.admin
            ) as response:
                self.assertEqual(response.status, 400)
                self.assertIn("error", await response.json())


class HttpUsageTests(UsageApiFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.requests = []
        self.include_tokens = True
        self.request_gate = None
        self.store.save(
            "cloud",
            "Cloud",
            "bailian_qwen_asr",
            {"apiKey": "fake-upstream", "previewIntervalMs": 0},
        )
        self.store.set_default("cloud")

        async def handle(request):
            self.requests.append(request)
            if self.request_gate:
                await self.request_gate.wait()
            payload = {"output": {"text": "测试结果。"}}
            if self.include_tokens:
                payload["usage"] = {"total_tokens": 7, "input_tokens": 5, "output_tokens": 2}
            return httpx.Response(200, json=payload)

        class MockBailian(BailianProvider):
            async def open(instance):
                await super().open()
                await instance.client.aclose()
                instance.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

        self.portal.factory = lambda profile: MockBailian(profile["configuration"])

    async def test_real_http_adapter_records_upstream_tokens_and_audio(self):
        socket = await self.session()
        await socket.send_bytes(struct.pack("<h", 1500) * 3200)
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["type"], "session.finished")
        quota = self.store.usage.quota("key", self.key_id)
        self.assertEqual(quota["reportedTokens"], 7)
        self.assertEqual(quota["usedSeconds"], 0.2)
        self.assertEqual(self.store.usage.quota("profile", "cloud")["usedSeconds"], 0.2)
        await socket.close()

    async def test_http_duration_quota_reserves_final_audio_and_rotates_default(self):
        self.store.usage.update_quota("profile", "cloud", {"remainingSeconds": 0.15})
        socket = await self.session()
        await socket.send_bytes(struct.pack("<h", 1500) * 3200)
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["type"], "session.finished")
        self.assertEqual(events[-1]["reason"], "quota_exhausted")
        self.assertEqual(self.store.usage.quota("key", self.key_id)["usedSeconds"], 0.15)
        quota = self.store.usage.quota("profile", "cloud")
        self.assertEqual(quota["usedSeconds"], 0.15)
        self.assertEqual(quota["remainingSeconds"], 0)
        self.assertFalse(quota["enabled"])
        self.assertEqual(self.store.settings()["defaultProfileId"], "local")
        await socket.close()

    async def test_http_vad_releases_discarded_silence_reservations(self):
        self.store.usage.update_quota("profile", "cloud", {"remainingSeconds": 1})
        socket = await self.session()
        await socket.send_bytes(bytes(64000))
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["type"], "session.finished")
        self.assertNotIn("reason", events[-1])
        self.assertEqual(self.store.usage.quota("key", self.key_id)["usedSeconds"], 2)
        quota = self.store.usage.quota("profile", "cloud")
        self.assertEqual(quota["remainingSeconds"], 1)
        self.assertEqual(quota["reservedSeconds"], 0)
        self.assertFalse(self.requests)
        await socket.close()

    async def test_token_limited_concurrent_sessions_make_only_one_paid_request(self):
        self.store.usage.update_quota("key", self.key_id, {"remainingTokens": 7})
        self.request_gate = asyncio.Event()
        first, second = await self.session(), await self.session()
        for socket in (first, second):
            await socket.send_bytes(struct.pack("<h", 1500) * 3200)
            await socket.send_json({"type": "audio.end"})
        deadline = time.monotonic() + 3
        while not self.requests and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        self.assertEqual(len(self.requests), 1)
        self.request_gate.set()
        events = await asyncio.gather(self.terminal(first), self.terminal(second))
        self.assertEqual(
            sorted(items[-1]["type"] for items in events), ["session.error", "session.finished"]
        )
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.usage.quota("key", self.key_id)["remainingTokens"], 0)
        await first.close()
        await second.close()

    async def test_missing_actual_token_usage_is_not_silently_counted_as_zero(self):
        self.include_tokens = False
        self.store.usage.update_quota("key", self.key_id, {"remainingTokens": 10})
        socket = await self.session()
        await socket.send_bytes(struct.pack("<h", 1500) * 3200)
        await socket.send_json({"type": "audio.end"})
        events = await self.terminal(socket)
        self.assertEqual(events[-1]["code"], "TOKEN_USAGE_UNAVAILABLE")
        self.assertTrue(self.store.usage.quota("key", self.key_id)["tokenBlocked"])
        await socket.close()
