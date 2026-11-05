"""Run the real extracted deb without system Python, outside source and production data."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--results", type=Path, default=ROOT / "test-results")
    args = parser.parse_args()
    dependencies = subprocess.check_output(
        ["dpkg-deb", "-f", str(args.package), "Depends"], text=True
    )
    assert "python3" not in dependencies, dependencies
    args.results.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable-portal-", dir=args.results) as directory:
        stage = Path(directory).resolve()
        subprocess.run(["dpkg-deb", "-x", str(args.package.resolve()), str(stage)], check=True)
        runtime = stage / "usr/lib/openasrportal/runtime/openasrportal-runtime"
        assert runtime.is_file()
        tools = stage / "tools"
        tools.mkdir()
        fake = tools / "python3"
        fake.write_text("#!/bin/sh\nexit 97\n")
        fake.chmod(0o755)
        env = {
            **os.environ,
            "PATH": str(tools) + ":/usr/bin:/bin",
            "PYTHONHOME": "/missing-python",
            "PYTHONPATH": "/missing-modules",
            "HOME": str(stage),
            "OPENASRPORTAL_API_KEY": "portable-recognition",
            "OPENASRPORTAL_ADMIN_KEY": "portable-admin",
        }
        configure = [str(runtime), "--configure-installation", "--root", str(stage)]
        subprocess.run(configure, env=env, cwd=stage, check=True)
        environment = stage / "etc/openasrportal/service.env"
        previous = environment.read_bytes()
        subprocess.run(configure, env=env, cwd=stage, check=True)
        assert previous == environment.read_bytes()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [
            str(stage / "usr/bin/openasrportal"),
            "--port",
            str(port),
            "--data-dir",
            str(stage / "data"),
        ]
        with (stage / "runtime.log").open("w") as log:
            child = subprocess.Popen(
                command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError((stage / "runtime.log").read_text())
                    try:
                        with urlopen(base + "/health", timeout=1) as response:
                            assert json.load(response)["status"] == "ok"
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("private Portal readiness timeout")

                def api(path, body=None, token=""):
                    with urlopen(
                        Request(
                            base + path,
                            data=None if body is None else json.dumps(body).encode(),
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": "Bearer " + token,
                            },
                        )
                    ) as response:
                        return json.load(response)

                assert "OPENASRPORTAL_API_KEY=" not in environment.read_text()
                assert "OPENASRPORTAL_ADMIN_KEY=" not in environment.read_text()
                status = api("/v1/admin/auth/status")
                password = "Portable administrator password 2026!"
                admin = api(
                    "/v1/admin/auth/setup",
                    {
                        "password": password,
                        "confirmPassword": password,
                        "setupChallenge": status["setupChallenge"],
                    },
                )["token"]
                key = api("/v1/admin/asr-keys", {"title": "portable-test"}, admin)["key"]
                headers = {"Authorization": "Bearer " + key}
                for path in ("/v1/capabilities", "/v1/hotwords", "/v1/hotwords/catalog"):
                    with urlopen(Request(base + path, headers=headers)) as response:
                        value = json.load(response)
                    if path.endswith("hotwords"):
                        assert value["settings"]["enabled"] is False
                    if path.endswith("catalog"):
                        assert any(source["id"] == "tech-ai" for source in value["sources"])
                with urlopen(base + "/admin") as response:
                    assert b"<html" in response.read().lower()
                with urlopen(
                    Request(base + "/v1/hotwords/catalog/tech-ai", headers=headers)
                ) as response:
                    assert len(json.load(response)["words"]) > 30
            finally:
                child.terminate()
                child.wait(timeout=20)
        print(
            "PASS portable Portal: no system Python ABI, private startup/setup, preserved credentials, API/admin/public words"
        )


if __name__ == "__main__":
    main()
