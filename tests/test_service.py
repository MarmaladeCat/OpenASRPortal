"""Portable service config, real process lifecycle and Windows packaging contract."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openasrportal.entrypoints.service import initialize, load_config, request_stop, write_json

ROOT = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="service-", dir=results)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "中文 service"
        self.directory.mkdir()
        self.config = self.directory / "service.json"

    def test_initialize_preserves_config_and_resolves_relative_data(self):
        initialize(self.config)
        original = self.config.read_bytes()
        initialize(self.config)
        self.assertEqual(self.config.read_bytes(), original)
        config = load_config(self.config)
        self.assertNotIn("apiKey", config)
        self.assertNotIn("adminKey", config)
        self.assertEqual(Path(config["dataDir"]), self.directory / "data")

    def test_invalid_config_is_not_overwritten(self):
        for patch in (
            {"schemaVersion": 2},
            {"port": True},
            {"port": 65536},
            {"host": ""},
            {"dataDir": ""},
        ):
            self.config.unlink(missing_ok=True)
            initialize(self.config)
            config = json.loads(self.config.read_text(encoding="utf-8"))
            config.update(patch)
            write_json(self.config, config)
            original = self.config.read_bytes()
            with self.assertRaises(ValueError):
                initialize(self.config)
            self.assertEqual(self.config.read_bytes(), original)

    def test_legacy_config_secrets_are_retired_without_becoming_authentication_defaults(self):
        initialize(self.config)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config.update(apiKey="old-recognition-secret", adminKey="old-management-secret")
        write_json(self.config, config)
        initialize(self.config)
        saved = self.config.read_text(encoding="utf-8")
        self.assertNotIn("old-recognition-secret", saved)
        self.assertNotIn("old-management-secret", saved)
        self.assertEqual(load_config(self.config)["port"], 10087)

    def test_stop_is_idempotent_and_rejects_path_traversal(self):
        request_stop(self.config)
        control = self.directory / "control"
        control.mkdir()
        write_json(control / "ready.json", {"instance": "../../bad"})
        with self.assertRaises(ValueError):
            request_stop(self.config)

    def test_real_service_restart_auth_and_graceful_stop(self):
        initialize(self.config)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            config["port"] = sock.getsockname()[1]
        write_json(self.config, config)
        command = [sys.executable, "-B", "-m", "openasrportal.entrypoints.service"]
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "OPENASRPORTAL_API_KEY": "wrong-inherited-key",
            "OPENASRPORTAL_ADMIN_KEY": "wrong-inherited-admin",
        }
        admin_token, client_key = "", ""

        def request(path, admin=False, body=None, key=None):
            with urlopen(
                Request(
                    f"http://127.0.0.1:{config['port']}" + path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={
                        "Authorization": "Bearer "
                        + (key if key is not None else admin_token if admin else client_key),
                        "Content-Type": "application/json",
                    },
                ),
                timeout=2,
            ) as response:
                return json.load(response)

        for iteration in range(2):
            # A stale request cannot shut down the next instance.
            control = self.directory / "control"
            control.mkdir(exist_ok=True)
            (control / ("0" * 32 + ".stop")).touch()
            with (self.directory / f"run-{iteration}.log").open("wb") as log:
                process = subprocess.Popen(
                    [*command, "run", "--config", str(self.config)],
                    cwd=self.directory,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            self.assertEqual(request("/health")["status"], "ok")
                            if (control / "ready.json").exists():
                                break
                        except URLError:
                            pass
                        if process.poll() is not None or time.monotonic() >= deadline:
                            self.fail("Service did not become ready; see " + str(self.directory))
                        time.sleep(0.1)
                    if iteration == 0:
                        nonce = request("/v1/admin/auth/status")["setupChallenge"]
                        admin_token = request(
                            "/v1/admin/auth/setup",
                            body={
                                "password": "Service test password 2026!",
                                "confirmPassword": "Service test password 2026!",
                                "setupChallenge": nonce,
                            },
                        )["token"]
                        client_key = request(
                            "/v1/admin/asr-keys", admin=True, body={"title": "service-test"}
                        )["key"]
                        with self.assertRaises(HTTPError) as error:
                            request("/v1/admin/contract", key="wrong-inherited-admin")
                        self.assertEqual(error.exception.code, 401)
                        error.exception.close()
                        with self.assertRaises(HTTPError) as error:
                            request("/v1/profiles", key="wrong-inherited-key")
                        self.assertEqual(error.exception.code, 401)
                        error.exception.close()
                        request(
                            "/v1/admin/profiles",
                            admin=True,
                            body={
                                "id": "service",
                                "title": "跨平台服务",
                                "provider": "openlocalasr",
                                "configuration": {"apiKey": "upstream-secret"},
                            },
                        )
                    profiles = request("/v1/profiles")
                    self.assertEqual(profiles["profiles"][0]["id"], "service")
                    self.assertNotIn("upstream-secret", json.dumps(profiles))
                    subprocess.run(
                        [*command, "stop", "--config", str(self.config)],
                        env=env,
                        check=True,
                        timeout=25,
                    )
                    self.assertEqual(process.wait(timeout=5), 0)
                    self.assertFalse((control / "ready.json").exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)

    def test_windows_wrapper_uses_shared_core_and_least_privilege(self):
        root = ET.parse(ROOT / "packaging/windows/OpenASRPortal.xml").getroot()
        self.assertEqual(root.findtext("serviceaccount/user"), "LocalService")
        self.assertEqual(root.findtext("serviceaccount/domain"), "NT AUTHORITY")
        self.assertEqual(root.findtext("startmode"), "Automatic")
        self.assertIn("openasrportal.entrypoints.service run", root.findtext("startarguments"))
        self.assertIn("openasrportal.entrypoints.service stop", root.findtext("stoparguments"))
        self.assertNotIn("apiKey", ET.tostring(root, encoding="unicode"))
        self.assertEqual(root.findtext("stoptimeout"), "30 sec")

    def test_occupied_port_fails_without_publishing_readiness(self):
        initialize(self.config)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            config["port"] = sock.getsockname()[1]
            write_json(self.config, config)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "openasrportal.entrypoints.service",
                    "run",
                    "--config",
                    str(self.config),
                ],
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "control/ready.json").exists())
        self.assertNotIn(b"OPENASRPORTAL_ADMIN_KEY", result.stdout)
        self.assertNotIn(b"OPENASRPORTAL_API_KEY", result.stdout)


if __name__ == "__main__":
    unittest.main()
