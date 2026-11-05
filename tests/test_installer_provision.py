import tempfile
import unittest
from pathlib import Path

from openasrportal.entrypoints.provision import provision
from openasrportal.storage.store import Store


class InstallerProvisionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "test-results"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="installer-provision-", dir=root)
        self.addCleanup(self.temp.cleanup)

    def test_explicit_owner_entrypoint_creates_local_input_without_default_password(self):
        result = provision(self.temp.name, "windows:test-user")
        store = Store(self.temp.name)
        self.assertFalse(store.auth.initialized())
        self.assertEqual(store.asr_keys()[0]["title"], "local-input")
        self.assertTrue(store.authorize_asr(result["key"]))
        self.assertFalse(store.auth.authorized(result["key"]))
        self.assertNotIn(result["key"].encode(), store.path.read_bytes())

    def test_reinstall_reuses_same_user_key_but_users_and_explicit_reinstall_after_revoke_are_isolated(
        self,
    ):
        first = provision(self.temp.name, "windows:first-user")
        self.assertEqual(first, provision(self.temp.name, "windows:first-user"))
        second = provision(self.temp.name, "windows:other-user")
        self.assertNotEqual(first["key"], second["key"])
        Store(self.temp.name).revoke_asr_key(first["generation"])
        replacement = provision(self.temp.name, "windows:first-user")
        self.assertNotEqual(first["key"], replacement["key"])
        store = Store(self.temp.name)
        self.assertIsNone(store.authorize_asr(first["key"]))
        self.assertTrue(store.authorize_asr(second["key"]))
        self.assertEqual(store.asr_keys()[0]["revoked"], True)


if __name__ == "__main__":
    unittest.main()
