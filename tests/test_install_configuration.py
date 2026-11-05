"""Installation upgrades retire environment credentials, preserving operational settings."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "installation_configure", ROOT / "packaging/configure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallationConfigurationTests(unittest.TestCase):
    def setUp(self):
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="install-config-", dir=results)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_fresh_install_has_loopback_and_no_credentials_or_handoff(self):
        MODULE.configure(self.root)
        environment = self.root / "etc/openasrportal/service.env"
        self.assertIn("OPENASRPORTAL_HOST=127.0.0.1", environment.read_text())
        self.assertNotIn("KEY=", environment.read_text())
        self.assertFalse(environment.with_name("client.json").exists())
        original = environment.read_bytes()
        MODULE.configure(self.root)
        self.assertEqual(original, environment.read_bytes())

    def test_upgrade_preserves_host_port_data_and_retires_only_generated_handoff(self):
        directory = self.root / "etc/openasrportal"
        directory.mkdir(parents=True)
        environment = directory / "service.env"
        environment.write_text(
            "# custom deployment\nOPENASRPORTAL_HOST=192.0.2.5\nOPENASRPORTAL_PORT=12087\n"
            "OPENASRPORTAL_DATA=/srv/portal\nOPENASRPORTAL_ADMIN_KEY=old-admin\nOPENASRPORTAL_API_KEY=old-client\n"
            "CUSTOM_SETTING=preserved\n",
            encoding="utf-8",
        )
        handoff = directory / "client.json"
        handoff.write_text(
            json.dumps({"url": "http://127.0.0.1:12087", "apiKey": "old-client", "profileId": ""})
        )
        MODULE.configure(self.root)
        saved = environment.read_text()
        for value in ("192.0.2.5", "12087", "/srv/portal", "CUSTOM_SETTING=preserved"):
            self.assertIn(value, saved)
        self.assertNotIn("old-admin", saved)
        self.assertNotIn("old-client", saved)
        self.assertFalse(handoff.exists())

    def test_unknown_handoff_content_is_not_deleted(self):
        directory = self.root / "etc/openasrportal"
        directory.mkdir(parents=True)
        handoff = directory / "client.json"
        handoff.write_text('{"userOwned":"keep me"}', encoding="utf-8")
        MODULE.configure(self.root)
        self.assertEqual(handoff.read_text(), '{"userOwned":"keep me"}')


if __name__ == "__main__":
    unittest.main()
