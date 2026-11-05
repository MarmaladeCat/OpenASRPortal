"""Native PowerShell launcher and restart checks with isolated Windows data."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "requires Windows PowerShell")
class WindowsStartTests(unittest.TestCase):
    def test_native_launcher_authentication_hotwords_and_persistent_restart(self):
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="windows-start-", dir=results) as temporary:
            data = Path(temporary) / "中文 data"
            env = {
                **os.environ,
                "OPENASRPORTAL_PYTHON": sys.executable,
                "OPENASRPORTAL_DATA": str(data),
                "OPENASRPORTAL_API_KEY": "test-asr",
                "OPENASRPORTAL_ADMIN_KEY": "test-admin",
            }
            admin_token, client_key = "", ""
            for iteration in range(2):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                with (Path(temporary) / f"server-{iteration}.log").open("wb") as log:
                    process = subprocess.Popen(
                        [
                            POWERSHELL,
                            "-NoProfile",
                            "-File",
                            str(ROOT / "scripts/start.ps1"),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        cwd=temporary,
                        env=env,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )

                    def request(path, key=None, body=None):
                        key = admin_token if key is None else key
                        value = None if body is None else json.dumps(body).encode()
                        with urlopen(
                            Request(
                                f"http://127.0.0.1:{port}" + path,
                                data=value,
                                headers={
                                    "Authorization": "Bearer " + key,
                                    "Content-Type": "application/json",
                                },
                            ),
                            timeout=2,
                        ) as response:
                            return json.load(response)

                    try:
                        deadline = time.monotonic() + 15
                        while True:
                            try:
                                health = request("/health")
                                break
                            except URLError:
                                if time.monotonic() >= deadline or process.poll() is not None:
                                    self.fail("Windows Portal did not become healthy")
                                time.sleep(0.1)
                        self.assertEqual(health["status"], "ok")
                        with self.assertRaises(HTTPError) as error:
                            request("/v1/admin/profiles", key="test-asr")
                        self.assertEqual(error.exception.code, 401)
                        error.exception.close()
                        if iteration == 0:
                            nonce = request("/v1/admin/auth/status")["setupChallenge"]
                            admin_token = request(
                                "/v1/admin/auth/setup",
                                body={
                                    "password": "Windows test password 2026!",
                                    "confirmPassword": "Windows test password 2026!",
                                    "setupChallenge": nonce,
                                },
                            )["token"]
                            client_key = request(
                                "/v1/admin/asr-keys", body={"title": "windows-test"}
                            )["key"]
                            request(
                                "/v1/admin/profiles",
                                body={
                                    "id": "windows",
                                    "title": "Windows 重启",
                                    "provider": "openlocalasr",
                                    "configuration": {"apiKey": "test-upstream"},
                                },
                            )
                        profiles = request("/v1/profiles", key=client_key)
                        self.assertEqual(profiles["profiles"][0]["id"], "windows")
                        self.assertNotIn("test-upstream", json.dumps(profiles))
                        self.assertFalse(
                            request("/v1/hotwords", key=client_key)["settings"]["enabled"]
                        )
                        self.assertTrue((data / "portal.db").is_file())
                    finally:
                        if process.poll() is None:
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=True,
                            )
                        process.wait(timeout=10)

    def test_help_restores_calling_environment(self):
        script = str(ROOT / "scripts/start.ps1").replace("'", "''")
        command = (
            f"& '{script}' --help; "
            "if ($env:PYTHONPATH -ne 'sentinel' -or $env:OPENASRPORTAL_DATA -ne 'original' "
            "-or $env:PYTHONDONTWRITEBYTECODE -ne '0') { throw 'environment changed' }"
        )
        subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command", command],
            env={
                **os.environ,
                "OPENASRPORTAL_PYTHON": sys.executable,
                "PYTHONPATH": "sentinel",
                "OPENASRPORTAL_DATA": "original",
                "PYTHONDONTWRITEBYTECODE": "0",
            },
            stdout=subprocess.DEVNULL,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
