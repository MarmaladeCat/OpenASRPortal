import json
import unittest

import test_hotwords

from openasrportal.domain.dictionaries import MAX_BYTES, parse_dictionary
from openasrportal.domain.hotwords import DEFAULTS, select_terms


class DictionaryFormatTests(unittest.TestCase):
    def test_thuocl_frequency_and_technical_symbols(self):
        result = parse_dictionary("Node.js\t12\nC++\t100\n机器学习\t10\nnode.js\t30\n单\t2\n")
        self.assertEqual(result["format"], "tsv")
        self.assertEqual([row["text"] for row in result["words"]], ["C++", "Node.js", "机器学习"])
        self.assertEqual(result["report"]["duplicates"], 1)
        self.assertEqual(result["report"]["skipped"], 1)
        self.assertEqual(result["words"][1]["frequency"], 30)
        self.assertEqual(result["words"][0]["weight"], 4)
        self.assertEqual(
            select_terms("doubao_realtime", result["words"], {**DEFAULTS, "enabled": True})[
                "appliedCount"
            ],
            1,
        )

    def test_rime_columns_percentages_and_import_tables(self):
        result = parse_dictionary(
            "\ufeff# dictionary\n---\nname: test\ncolumns: [code, text, weight]\nimport_tables:\n  - other\n...\nshen\t神经网络\t99%\npython\tPython\t9000\n"
        )
        self.assertEqual([row["text"] for row in result["words"]], ["Python", "神经网络"])
        self.assertEqual(result["words"][0]["weight"], 4)
        self.assertIn("other", result["report"]["warnings"][0])
        self.assertEqual(
            parse_dictionary(
                "---\ncolumns:\n - text\n - weight\n - code\n...\n词库\t1000\tci ku\n"
            )["words"][0]["text"],
            "词库",
        )

    def test_plain_csv_json_and_custom_phrase(self):
        self.assertEqual(
            parse_dictionary("Python|3\n# comment\n机器学习\n")["words"][0]["weight"], 3
        )
        csv = parse_dictionary('text,weight,frequency\n"SQL Server",3,25\nPython,4,100\n')
        self.assertEqual(csv["words"][0]["text"], "Python")
        self.assertEqual(csv["words"][1]["weight"], 3)
        for content in (
            '["Python", {"text":"机器学习", "frequency":10}]',
            '{"vocabulary":{"Python":3}}',
        ):
            self.assertTrue(parse_dictionary(content)["words"])
        self.assertEqual(
            parse_dictionary("机器学习\tji qi xue xi\t100\n")["words"][0]["text"], "机器学习"
        )

    def test_empty_binary_invalid_rime_and_size_limit_are_rejected(self):
        for content in (
            "",
            "\0binary",
            "---\nname: schema\n",
            "---\nimport_tables:\n - child\n...\n",
            "x" * (MAX_BYTES + 1),
        ):
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                parse_dictionary(content)


class DictionaryAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_hotwords.HotwordAPITests.asyncSetUp
    asyncTearDown = test_hotwords.HotwordAPITests.asyncTearDown
    request = test_hotwords.HotwordAPITests.request

    async def test_admin_and_client_share_dictionary_revision_and_settings(self):
        key_id = self.store.asr_keys()[0]["id"]
        admin = f"/v1/admin/asr-keys/{key_id}/hotwords"
        # Admin targets the hash internally, without revealing any plaintext key.
        self.assertEqual((await self.request("GET", admin))[0], 401)
        code, initial = await self.request("GET", admin, key="admin-key")
        self.assertEqual(code, 200)
        self.assertEqual(initial["revision"], 0)
        payload = {
            "revision": 0,
            "title": "编程",
            "format": "rime",
            "content": "---\nname: code\n...\nPython\tpython\t900\n机器学习\tji qi xue xi\t100\n",
        }
        code, added = await self.request("POST", admin + "/dictionaries", payload, key="admin-key")
        self.assertEqual(code, 201)
        identity = added["importedDictionaryId"]
        _, client = await self.request("GET")
        self.assertEqual(client["dictionaries"], added["dictionaries"])
        self.assertEqual(client["terms"], [])
        self.assertFalse(client["dictionaries"][0]["enabled"])
        self.assertNotIn("alice-key", json.dumps(added))
        self.assertEqual((await self.request("GET", key=self.bob))[1]["dictionaries"], [])
        _, session = await self.request("POST", "/v1/sessions", {"profileId": "bailian"})
        snapshot = self.portal.sessions[session["sessionId"]].profile["configuration"]["hotwords"]
        self.assertEqual(snapshot, [])
        path = "/v1/hotwords/dictionaries/" + identity
        code, words = await self.request("GET", path)
        self.assertEqual(code, 200)
        self.assertEqual({word["text"] for word in words["words"]}, {"Python", "机器学习"})
        self.assertEqual((await self.request("GET", path, key=self.bob))[0], 404)
        self.assertEqual(
            (await self.request("PATCH", path, {"revision": 0, "patch": {"enabled": False}}))[0],
            409,
        )
        self.assertEqual(
            (
                await self.request(
                    "PATCH", path, {"revision": 0, "patch": {"enabled": False}}, key=self.bob
                )
            )[0],
            404,
        )
        code, disabled = await self.request(
            "PATCH", path, {"revision": 1, "patch": {"enabled": False}}
        )
        self.assertEqual(code, 200)
        self.assertEqual(disabled["terms"], [])
        self.assertEqual(snapshot, [])
        _, admin_read = await self.request("GET", admin, key="admin-key")
        self.assertEqual(admin_read["revision"], disabled["revision"])
        self.assertFalse(admin_read["dictionaries"][0]["enabled"])
        await self.request(
            "PATCH",
            admin,
            {"revision": 2, "settings": {"manualTerms": [{"text": "神经网络"}]}},
            key="admin-key",
        )
        self.assertEqual(
            (await self.request("GET"))[1]["settings"]["manualTerms"][0]["text"], "神经网络"
        )
        code, removed = await self.request(
            "DELETE", admin + "/dictionaries/" + identity, {"revision": 3}, key="admin-key"
        )
        self.assertEqual(code, 200)
        self.assertEqual(removed["dictionaries"], [])
        self.assertEqual((await self.request("GET"))[1]["dictionaries"], [])

    async def test_preview_does_not_mutate_and_catalog_source_import_is_explicit(self):
        code, catalog = await self.request("GET", "/v1/hotwords/catalog")
        self.assertEqual(code, 200)
        self.assertIn("rime", catalog["formats"])
        code, preview = await self.request(
            "POST", "/v1/hotwords/dictionaries", {"preview": True, "content": "Python\nC++\n"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(preview["report"]["wordCount"], 2)
        self.assertEqual({word["text"] for word in preview["words"]}, {"Python", "C++"})
        self.assertEqual((await self.request("GET"))[1]["revision"], 0)
        code, added = await self.request(
            "POST", "/v1/hotwords/dictionaries", {"sourceId": "tech-ai", "revision": 0}
        )
        self.assertEqual(code, 201)
        self.assertGreater(added["importReport"]["wordCount"], 30)
        self.assertEqual(
            (
                await self.request(
                    "POST",
                    "/v1/hotwords/dictionaries",
                    {"sourceId": "https://localhost/private", "revision": 1},
                )
            )[0],
            400,
        )

    async def test_only_saved_personal_table_is_used_by_all_clients_of_same_key(self):
        _, before = await self.request("GET")
        self.assertFalse(before["settings"]["enabled"])
        _, recommendations = await self.request(
            "POST", "/v1/hotwords/dictionaries", {"sourceId": "tech-ai", "preview": True}
        )
        self.assertGreater(len(recommendations["words"]), 30)
        self.assertEqual((await self.request("GET"))[1], before)
        # Even a legacy client's enabled library is only a recommendation snapshot.
        _, imported = await self.request(
            "POST",
            "/v1/hotwords/dictionaries",
            {"revision": 0, "title": "推荐", "content": "Python\n机器学习\n"},
        )
        await self.request(
            "PATCH",
            "/v1/hotwords/dictionaries/" + imported["importedDictionaryId"],
            {"revision": 1, "patch": {"enabled": True}},
        )
        _, saved = await self.request(
            "PATCH",
            body={
                "revision": 2,
                "settings": {
                    "enabled": True,
                    "autoLearn": True,
                    "manualTerms": [{"text": "神经网络", "weight": 3}],
                },
            },
        )
        self.assertEqual((await self.request("GET"))[1]["settings"], saved["settings"])
        self.assertEqual((await self.request("GET", key=self.bob))[1]["terms"], [])
        _, session = await self.request("POST", "/v1/sessions", {"profileId": "bailian"})
        snapshot = self.portal.sessions[session["sessionId"]].profile["configuration"]["hotwords"]
        self.assertEqual(snapshot, [{"text": "神经网络", "weight": 3}])
        await self.request("PATCH", body={"revision": 3, "settings": {"manualTerms": []}})
        self.assertEqual((await self.request("GET"))[1]["terms"], [])
        _, next_session = await self.request("POST", "/v1/sessions", {"profileId": "bailian"})
        self.assertEqual(
            self.portal.sessions[next_session["sessionId"]].profile["configuration"]["hotwords"], []
        )
        self.assertEqual(snapshot, [{"text": "神经网络", "weight": 3}])

    async def test_personal_words_remain_disabled_until_explicit_opt_in(self):
        _, saved = await self.request(
            "PATCH",
            body={
                "revision": 0,
                "settings": {"manualTerms": [{"text": "机器学习"}]},
            },
        )
        self.assertEqual(saved["selection"]["appliedCount"], 0)
        self.assertEqual(saved["selection"]["omitted"][0]["reason"], "disabled")
        await self.request("PATCH", body={"revision": 1, "settings": {"enabled": True}})
        self.assertEqual((await self.request("GET"))[1]["selection"]["appliedCount"], 1)
        await self.request("PATCH", body={"revision": 2, "settings": {"enabled": False}})
        self.assertEqual((await self.request("GET"))[1]["selection"]["appliedCount"], 0)
