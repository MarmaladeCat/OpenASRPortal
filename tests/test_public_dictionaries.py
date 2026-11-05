import json
import unittest
from unittest.mock import patch

import httpx
import test_hotwords
from support_auth import portal_for_tests as Portal

from openasrportal.domain.dictionaries import parse_dictionary
from openasrportal.storage.store import Store

ADMIN = "/v1/admin/hotwords/public-dictionaries"


class PublicDictionaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_hotwords.HotwordAPITests.asyncSetUp
    asyncTearDown = test_hotwords.HotwordAPITests.asyncTearDown
    request = test_hotwords.HotwordAPITests.request

    async def admin(self, method, path=ADMIN, body=None):
        return await self.request(method, path, body, key="admin-key")

    async def test_permissions_and_shared_catalog_without_personal_mutations(self):
        for key in ("", "bad", "alice-key", self.bob):
            self.assertEqual((await self.request("GET", ADMIN, key=key))[0], 401)
            self.assertEqual(
                (await self.request("POST", ADMIN, {"title": "禁止"}, key=key))[0], 401
            )
        code, listing = await self.admin("GET")
        self.assertEqual(code, 200)
        self.assertEqual(
            {row["id"] for row in listing["dictionaries"]},
            {"tech-ai", "tech-computing", "tech-programming"},
        )
        _, alice = await self.request("GET", "/v1/hotwords/catalog")
        _, bob = await self.request("GET", "/v1/hotwords/catalog", key=self.bob)
        self.assertEqual(alice, bob)
        path = "/v1/hotwords/catalog/tech-ai"
        self.assertEqual((await self.request("GET", path, key=""))[0], 401)
        code, words = await self.request("GET", path)
        self.assertEqual(code, 200)
        self.assertGreater(len(words["words"]), 30)
        self.assertEqual((await self.request("GET", path, key=self.bob))[1], words)
        self.assertEqual((await self.request("GET"))[1]["revision"], 0)
        self.assertEqual((await self.request("GET"))[1]["terms"], [])

    async def test_admin_crud_publication_and_personal_copies_are_independent(self):
        code, created = await self.admin(
            "POST",
            body={
                "title": "医疗",
                "description": "医学用语",
                "license": "自建词表",
                "homepage": "https://example.org/terms",
                "content": "神经网络|3\n机器学习|4\n",
            },
        )
        self.assertEqual(code, 201)
        self.assertEqual(created["revision"], 1)
        identity = created["id"]
        path = ADMIN + "/" + identity
        client_path = "/v1/hotwords/catalog/" + identity
        _, exported = await self.admin("GET", path)
        self.assertEqual(exported, created)
        _, preview = await self.request(
            "POST",
            "/v1/hotwords/dictionaries",
            {
                "sourceId": identity,
                "preview": True,
            },
        )
        self.assertEqual(preview["words"], created["words"])
        await self.request(
            "PATCH",
            body={
                "revision": 0,
                "settings": {"enabled": True, "manualTerms": [{"text": "神经网络", "weight": 3}]},
            },
        )
        _, personal = await self.request("GET")
        code, updated = await self.admin(
            "PATCH",
            path,
            {
                "revision": 1,
                "title": "新版医疗",
                "content": "医学成像|5\n",
                "enabled": False,
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(updated["revision"], 2)
        self.assertEqual((await self.request("GET", client_path))[0], 404)
        self.assertNotIn(
            identity,
            {
                row["id"]
                for row in (await self.request("GET", "/v1/hotwords/catalog"))[1]["sources"]
            },
        )
        self.assertEqual(
            (await self.admin("PATCH", path, {"revision": 1, "title": "旧编辑"}))[0], 409
        )
        self.assertEqual((await self.admin("DELETE", path, {"revision": 1}))[0], 409)
        self.assertEqual((await self.request("GET"))[1], personal)
        await self.admin("PATCH", path, {"revision": 2, "enabled": True})
        self.assertEqual(
            (await self.request("GET", client_path))[1]["words"][0]["text"], "医学成像"
        )
        self.assertEqual((await self.admin("DELETE", path, {"revision": 3}))[0], 200)
        self.assertEqual((await self.request("GET", client_path))[0], 404)
        self.assertEqual((await self.request("GET"))[1], personal)

    async def test_builtin_edits_and_deletions_survive_restart(self):
        await self.admin(
            "PATCH",
            ADMIN + "/tech-ai",
            {"revision": 1, "title": "管理员精选", "content": "自定义人工智能|4\n"},
        )
        await self.admin("DELETE", ADMIN + "/tech-computing", {"revision": 1})
        restarted = Store(self.temp.name)
        Portal(restarted, "alice-key", "admin-key")
        self.assertEqual(restarted.public_dictionaries.get("tech-ai")["title"], "管理员精选")
        self.assertIsNone(restarted.public_dictionaries.get("tech-computing"))
        self.assertEqual((await self.request("GET", "/v1/hotwords/catalog/tech-computing"))[0], 404)
        self.assertEqual(
            (
                await self.request(
                    "POST",
                    "/v1/hotwords/dictionaries",
                    {"sourceId": "tech-computing", "preview": True},
                )
            )[0],
            400,
        )

    async def test_file_and_online_import_preview_and_export_roundtrip(self):
        before = (await self.admin("GET"))[1]
        code, preview = await self.admin(
            "POST",
            body={
                "preview": True,
                "format": "rime",
                "content": "---\nname: terms\n...\nPython\tpython\t900\nNode.js\tnode\t100\n",
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(preview["report"]["wordCount"], 2)
        self.assertEqual((await self.admin("GET"))[1], before)
        with patch(
            "openasrportal.api.server.source_content",
            return_value=(
                "医学成像\t80\n",
                "tsv",
                {"id": "thuocl-it", "title": "外部来源", "sha256": "test"},
            ),
        ):
            code, created = await self.admin("POST", body={"sourceId": "thuocl-it"})
        self.assertEqual(code, 201)
        self.assertEqual(created["title"], "外部来源")
        self.assertEqual(parse_dictionary(json.dumps(created), "json")["words"], created["words"])
        with patch(
            "openasrportal.api.server.source_content", side_effect=httpx.ConnectError("offline")
        ):
            self.assertEqual(
                (await self.admin("POST", body={"sourceId": "thuocl-it", "preview": True}))[0], 502
            )

    async def test_empty_table_and_invalid_metadata_and_imports(self):
        code, empty = await self.admin("POST", body={"title": "先建空表", "enabled": False})
        self.assertEqual(code, 201)
        self.assertEqual(empty["words"], [])
        for body in (
            {"title": ""},
            {"title": "a" * 101},
            {"title": "词表", "enabled": 1},
            {"title": "词表", "homepage": "javascript:alert(1)"},
            {"title": "词表", "sourceId": "https://localhost/private"},
            {"title": "词表", "sourceId": ["tech-ai"]},
            {"title": "词表", "sourceId": None},
            {"title": "词表", "content": "Python", "format": "pdf"},
            {"title": "词表", "content": "Python", "sourceId": "thuocl-it"},
            {"title": "词表", "preview": 1},
        ):
            with self.subTest(body=body):
                self.assertEqual((await self.admin("POST", body=body))[0], 400)
        code, error = await self.admin("PATCH", ADMIN + "/" + empty["id"], {"title": "没带版本"})
        self.assertEqual(code, 409)
        self.assertEqual(error["error"]["code"], "PUBLIC_DICTIONARY_CONFLICT")
