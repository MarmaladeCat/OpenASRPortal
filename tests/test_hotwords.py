"""Personal vocabulary isolation, rolling counts, wire payloads and session snapshots."""

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from support_auth import fixture_token
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.domain.asr_protocol import text_event
from openasrportal.domain.config import validate_config
from openasrportal.domain.hotwords import DEFAULTS, select_terms, validate_settings
from openasrportal.providers.bailian_asr import BailianProvider
from openasrportal.storage.store import Store

RESULTS = Path(__file__).resolve().parents[1] / "test-results"


def digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


class HotwordStoreTests(unittest.TestCase):
    def setUp(self):
        RESULTS.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="hotwords-", dir=RESULTS)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.words = self.store.hotwords

    def final(self, identity, text="麒麟 Kubernetes Kubernetes", kind="transcript.final"):
        self.words.observe("alice", {"type": kind, "utteranceId": identity, "text": text})

    def test_opt_in_final_deduplication_and_word_segmentation(self):
        self.final("disabled")
        self.assertEqual(self.words.listing("alice")["learnedTerms"], [])
        self.words.update("alice", {"autoLearn": True, "minFrequency": 2}, 0)
        self.final("preview", kind="transcript.partial")
        self.final("first")
        self.final("first")
        self.final("second", "麒麟")
        listing = self.words.listing("alice")
        counts = {term["text"]: term["frequency"] for term in listing["learnedTerms"]}
        self.assertEqual(counts, {"麒麟": 2, "kubernetes": 2})
        self.assertEqual(
            listing["terms"], []
        )  # Statistics are recommendations, not personal terms.
        self.assertEqual(self.words.listing("bob")["terms"], [])
        self.assertEqual(Store(self.temp.name).hotwords.listing("alice")["terms"], listing["terms"])
        with self.store.connection() as db:
            content = " ".join(db.iterdump())
        self.assertNotIn("麒麟 Kubernetes Kubernetes", content)
        self.words.update("alice", {"autoLearn": False}, 1)
        self.final("off-again")
        self.assertEqual(self.words.listing("alice")["learnedTerms"], listing["learnedTerms"])
        self.assertEqual(self.words.listing("alice")["terms"], [])

    def test_window_expiry_exclusion_manual_priority_and_clear(self):
        self.words.update(
            "alice",
            {
                "enabled": True,
                "autoLearn": True,
                "minFrequency": 2,
                "windowDays": 7,
                "maxWords": 1,
                "manualTerms": [{"text": "自定义词"}],
            },
            0,
        )
        now = time.time()
        with patch("openasrportal.storage.hotwords.time.time", return_value=now - 10 * 86400):
            self.final("old", "旧词旧词")
        self.final("new")
        self.final("another", "麒麟")
        listing = self.words.listing("alice", "bailian_qwen_asr")
        self.assertEqual(listing["selection"]["terms"][0]["text"], "自定义词")
        self.assertEqual(listing["selection"]["appliedCount"], 1)
        self.assertNotIn("旧词", {term["text"] for term in listing["learnedTerms"]})
        self.words.update("alice", {"excludedTerms": ["麒麟", "Kubernetes"]}, 1)
        self.assertEqual(len(self.words.listing("alice")["terms"]), 1)
        self.words.clear_statistics("alice")
        self.final("new")  # Old utterances cannot repopulate cleared statistics.
        cleared = self.words.listing("alice")
        self.assertEqual(cleared["learnedTerms"], [])
        self.assertEqual(cleared["terms"][0]["text"], "自定义词")

    def test_validation_and_provider_limits(self):
        for patch_value in (
            {"autoLearn": 1},
            {"windowDays": 91},
            {"maxWords": True},
            {"minFrequency": 1},
            {"manualTerms": [{"text": "a"}]},
            {"manualTerms": [{"text": "热词", "weight": 50}]},
            {"manualTerms": [{"text": "ABC"}, {"text": "abc"}]},
        ):
            with self.subTest(patch=patch_value), self.assertRaises(ValueError):
                validate_settings(patch_value, DEFAULTS)
        terms = [{"text": f"专有词{chr(0x4E00 + index)}", "weight": 4} for index in range(100)]
        enabled = {**DEFAULTS, "enabled": True}
        selected = select_terms("doubao_realtime", terms, enabled)
        self.assertLess(selected["appliedCount"], 100)
        self.assertLessEqual(selected["budgetUsed"], 100)
        self.assertEqual(selected["capability"]["maxTokens"], 100)
        self.assertEqual(select_terms("openlocalasr", terms, DEFAULTS)["appliedCount"], 0)
        bailian = select_terms("bailian_qwen_asr", terms * 25, {**enabled, "maxWords": 2000})
        self.assertEqual(bailian["appliedCount"], 2000)
        invalid = [{"text": "太长" * 8}, {"text": "one two three four five six seven eight"}]
        self.assertEqual(select_terms("bailian_qwen_asr", invalid, enabled)["appliedCount"], 0)

    def test_existing_database_upgrade_preserves_profiles_keys_and_quotas(self):
        self.store.save("legacy", "已有豆包", "doubao_realtime", {"apiKey": "legacy-upstream"})
        key = self.store.create_asr_key("已有客户端")
        self.store.usage.update_quota("profile", "legacy", {"remainingSeconds": 120})
        previous = self.store.get("legacy")
        quota = self.store.usage.quota("profile", "legacy")
        with self.store.connection() as db:
            # Simulate the deployed schema before the additive hotword tables existed.
            for table in ("hotword_settings", "hotword_counts", "hotword_finals"):
                db.execute(f"DROP TABLE {table}")
        upgraded = Store(self.temp.name)
        self.assertEqual(upgraded.get("legacy"), previous)
        self.assertEqual(upgraded.settings()["defaultProfileId"], "legacy")
        self.assertEqual(upgraded.usage.quota("profile", "legacy"), quota)
        self.assertEqual(upgraded.authorize_asr(key["key"]), digest(key["key"]))
        self.assertEqual(upgraded.reveal_asr_key(key["id"]), key["key"])
        self.assertFalse(upgraded.hotwords.listing(digest(key["key"]))["settings"]["autoLearn"])


class LearningProvider(FakeProvider):
    async def send_audio(self, data, last=False):
        if last:
            raw = text_event("final_result", "麒麟 Kubernetes Kubernetes", 0, 500)
            await self.queue.put(([raw, raw], True))


class HotwordAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        RESULTS.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="hotwords-api-", dir=RESULTS)
        self.store = Store(self.temp.name)
        self.store.save("doubao", "豆包", "doubao_realtime", {"apiKey": "fake-upstream"})
        self.store.save("bailian", "百炼", "bailian_qwen_asr", {"apiKey": "fake-upstream-2"})
        self.portal = Portal(self.store, "alice-key", "admin-key", factory=LearningProvider)
        self.bob = self.store.create_asr_key("Bob")["key"]
        self.server = TestServer(self.portal.app())
        await self.server.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    async def request(self, method, path="/v1/hotwords", body=None, key="alice-key"):
        key = fixture_token(self.portal, key)
        async with self.client.request(
            method,
            self.server.make_url(path),
            json=body,
            headers={"Authorization": "Bearer " + key},
        ) as response:
            return response.status, await response.json()

    async def test_isolated_crud_permissions_revision_and_capability(self):
        for key in ("", "bad", "admin-key"):
            self.assertEqual((await self.request("GET", key=key))[0], 401)
        _, initial = await self.request("GET")
        self.assertFalse(initial["settings"]["enabled"])
        self.assertFalse(initial["settings"]["autoLearn"])
        self.assertEqual(initial["selection"]["capability"]["maxTokens"], 100)
        body = {
            "revision": 0,
            "settings": {"enabled": True, "manualTerms": [{"text": "麒麟", "weight": 3}]},
        }
        code, updated = await self.request("PATCH", body=body)
        self.assertEqual(code, 200)
        self.assertEqual(updated["selection"]["terms"][0]["text"], "麒麟")
        self.assertEqual((await self.request("GET", key=self.bob))[1]["terms"], [])
        self.assertEqual((await self.request("PATCH", body=body))[0], 409)
        self.assertEqual((await self.request("PATCH", body=[]))[0], 400)
        self.assertEqual((await self.request("GET", "/v1/hotwords?profileId=missing"))[0], 404)
        _, bailian = await self.request("GET", "/v1/hotwords?profileId=bailian")
        self.assertEqual(bailian["selection"]["capability"]["maxEntries"], 2000)
        self.store.revoke_asr_key(self.store.asr_keys()[-1]["id"])
        self.assertEqual((await self.request("GET", key=self.bob))[0], 401)

    async def test_session_snapshot_and_only_normalized_finals_are_learned(self):
        await self.request(
            "PATCH",
            body={
                "revision": 0,
                "settings": {
                    "enabled": True,
                    "autoLearn": True,
                    "minFrequency": 2,
                    "manualTerms": [{"text": "麒麟"}],
                },
            },
        )
        _, session = await self.request("POST", "/v1/sessions", {"profileId": "doubao"})
        snapshot = self.portal.sessions[session["sessionId"]].profile["configuration"]
        self.assertEqual(snapshot["hotwords"], [{"text": "麒麟", "weight": 4}])
        await self.request(
            "PATCH", body={"revision": 1, "settings": {"manualTerms": [{"text": "另一个词"}]}}
        )
        self.assertEqual(snapshot["hotwords"][0]["text"], "麒麟")
        self.assertNotIn("hotwords", self.store.get("doubao")["configuration"])
        socket = await self.client.ws_connect(
            self.server.make_url(session["streamPath"] + "?ticket=" + session["ticket"])
        )
        ready = await socket.receive_json()
        self.assertEqual(ready["hotwords"]["appliedCount"], 1)
        await socket.receive_json()  # partial, never learned
        await socket.send_json({"type": "audio.end"})
        self.assertEqual((await socket.receive_json())["type"], "transcript.final")
        self.assertEqual((await socket.receive_json())["finalCount"], 1)
        await socket.close()
        _, listing = await self.request("GET")
        self.assertEqual(
            {term["text"]: term["frequency"] for term in listing["learnedTerms"]},
            {"麒麟": 1, "kubernetes": 2},
        )
        self.assertEqual((await self.request("GET", key=self.bob))[1]["learnedTerms"], [])
        await self.request("DELETE", "/v1/hotwords/statistics")
        self.assertEqual((await self.request("GET"))[1]["learnedTerms"], [])

    async def test_bailian_inline_vocabulary_wire_payload(self):
        config = validate_config("bailian_qwen_asr", {"apiKey": "test"})
        config["hotwords"] = [{"text": "麒麟", "weight": 3}, {"text": "Kubernetes", "weight": 4}]
        provider = BailianProvider(config)
        self.assertEqual(provider.parameters()["vocabulary"], {"麒麟": 3, "Kubernetes": 4})
