"""Installation upgrades retire environment credentials, preserving operational settings."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        environment = self.root / "var/lib/openasr/portal/service.env"
        self.assertIn("OPENASRPORTAL_HOST=127.0.0.1", environment.read_text())
        self.assertNotIn("KEY=", environment.read_text())
        self.assertFalse(environment.with_name("client.json").exists())
        original = environment.read_bytes()
        state = environment.with_name("installation.json")
        self.assertEqual(json.loads(state.read_text())["operation"], "first-install")
        MODULE.configure(self.root)
        self.assertEqual(original, environment.read_bytes())
        self.assertEqual(json.loads(state.read_text())["operation"], "reinstall")
        MODULE.configure(self.root, "1.0.0")
        self.assertEqual(json.loads(state.read_text())["operation"], "upgrade")

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
        self.assertEqual(saved, (self.root / "var/lib/openasr/portal/service.env").read_text())
        self.assertEqual(
            (self.root / "usr/share/openasrportal/admin.url").read_text().strip(),
            "http://192.0.2.5:12087/admin",
        )

    def test_default_data_migration_preserves_bytes_and_does_not_repeat(self):
        legacy = self.root / "etc/openasrportal"
        legacy.mkdir(parents=True)
        (legacy / "service.env").write_text(
            'OPENASRPORTAL_DATA="/var/lib/openasrportal"\nOPENASRPORTAL_PORT=12087\n'
        )
        data = self.root / "var/lib/openasrportal"
        data.mkdir(parents=True)
        (data / "portal.db").write_bytes(b"isolated database fixture")
        (data / "asr-key-vault.key").write_bytes(b"isolated vault fixture")
        MODULE.configure(self.root, "1.0.0")
        installed = self.root / "var/lib/openasr/portal/data"
        self.assertEqual((data / "portal.db").read_bytes(), (installed / "portal.db").read_bytes())
        self.assertEqual(
            (data / "asr-key-vault.key").read_bytes(),
            (installed / "asr-key-vault.key").read_bytes(),
        )
        (installed / "portal.db").write_bytes(b"new data")
        MODULE.configure(self.root)
        self.assertEqual((installed / "portal.db").read_bytes(), b"new data")
        self.assertEqual(
            (self.root / "usr/share/openasrportal/admin.url").read_text().strip(),
            "http://127.0.0.1:12087/admin",
        )

    def test_removed_package_is_reinstall_even_when_dpkg_passes_previous_version(self):
        MODULE.configure(self.root)
        directory = self.root / "var/lib/openasr/portal"
        (directory / "pending-operation").write_text("install\n")
        MODULE.configure(self.root, "1.0.0")
        self.assertEqual(
            json.loads((directory / "installation.json").read_text())["operation"], "reinstall"
        )

    def test_interrupted_legacy_copy_can_be_retried_without_accepting_partial_data(self):
        legacy = self.root / "etc/openasrportal"
        legacy.mkdir(parents=True)
        (legacy / "service.env").write_text("OPENASRPORTAL_DATA=/var/lib/openasrportal\n")
        source = self.root / "var/lib/openasrportal"
        source.mkdir(parents=True)
        (source / "portal.db").write_bytes(b"complete database fixture")
        with patch.object(MODULE.shutil, "copytree", side_effect=OSError("interrupted copy")):
            with self.assertRaises(OSError):
                MODULE.configure(self.root)
        destination = self.root / "var/lib/openasr/portal/data"
        self.assertFalse(destination.exists())
        MODULE.configure(self.root)
        self.assertEqual(
            (destination / "portal.db").read_bytes(), (source / "portal.db").read_bytes()
        )

    def test_custom_quoted_path_does_not_migrate_unused_legacy_data(self):
        legacy = self.root / "etc/openasrportal"
        legacy.mkdir(parents=True)
        (legacy / "service.env").write_text('OPENASRPORTAL_DATA="/srv/custom portal"\n')
        data = self.root / "var/lib/openasrportal"
        data.mkdir(parents=True)
        (data / "portal.db").write_bytes(b"unused old database")
        MODULE.configure(self.root)
        self.assertFalse((self.root / "var/lib/openasr/portal/data/portal.db").exists())
        self.assertEqual(
            MODULE.environment_values((legacy / "service.env").read_text())["OPENASRPORTAL_DATA"],
            "/srv/custom portal",
        )
        dropin = self.root / "etc/systemd/system/openasrportal.service.d/20-data-directory.conf"
        self.assertIn('ReadWritePaths="/srv/custom portal"', dropin.read_text())
        self.assertIn('BindPaths="/srv/custom portal"', dropin.read_text())

    def test_custom_sandbox_path_escapes_systemd_specifiers_and_rejects_root(self):
        MODULE.configure_data_access(self.root, '/srv/100% "portal"')
        dropin = self.root / "etc/systemd/system/openasrportal.service.d/20-data-directory.conf"
        self.assertIn(r'ReadWritePaths="/srv/100%% \"portal\""', dropin.read_text())
        with self.assertRaises(ValueError):
            MODULE.configure_data_access(self.root, "/")
        with self.assertRaises(ValueError):
            MODULE.configure_data_access(self.root, "/srv/portal\n[Service]")

    def test_unknown_handoff_content_is_not_deleted(self):
        directory = self.root / "etc/openasrportal"
        directory.mkdir(parents=True)
        handoff = directory / "client.json"
        handoff.write_text('{"userOwned":"keep me"}', encoding="utf-8")
        MODULE.configure(self.root)
        self.assertEqual(handoff.read_text(), '{"userOwned":"keep me"}')


if __name__ == "__main__":
    unittest.main()
