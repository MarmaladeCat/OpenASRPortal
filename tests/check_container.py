"""Opt-in Portal container smoke: non-root, public API, persistent keys, healthcheck."""

import argparse
import json
import subprocess
import tarfile
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def docker(*arguments):
    return subprocess.check_output(["docker", *arguments], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="openasrportal:release-test")
    parser.add_argument(
        "--archive", type=Path, help="verify the standalone Docker deployment archive"
    )
    args = parser.parse_args()
    if args.archive:
        with tarfile.open(args.archive) as archive:
            assert set(archive.getnames()) == {
                "OpenASRPortal",
                "OpenASRPortal/image.tar",
                "OpenASRPortal/image.json",
                "OpenASRPortal/compose.yaml",
                "OpenASRPortal/.env.example",
                "OpenASRPortal/README.md",
                "OpenASRPortal/LICENSE",
                "OpenASRPortal/compose.https.yaml",
                "OpenASRPortal/nginx",
                "OpenASRPortal/nginx/portal.conf",
                "OpenASRPortal/create_tls_certificate.py",
            }
            assert archive.getmember("OpenASRPortal/image.tar").size > 0
            assert (
                archive.extractfile("OpenASRPortal/LICENSE").read()
                == (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes()
            )
            record = json.load(archive.extractfile("OpenASRPortal/image.json"))
            actual = json.loads(docker("image", "inspect", args.image))[0]
            assert record["id"] == actual["Id"] and record["tag"] == args.image
            assert record["platform"] == actual["Os"] + "/" + actual["Architecture"]
            assert b"@IMAGE@" not in archive.extractfile("OpenASRPortal/.env.example").read()
            assert b"build:" not in archive.extractfile("OpenASRPortal/compose.yaml").read()
    name = "openasrportal-test-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    docker("volume", "create", volume)
    try:
        original = None
        public_id = None
        for _ in range(2):
            docker(
                "run",
                "-d",
                "--name",
                name,
                "--health-interval=1s",
                "-p",
                "127.0.0.1::10087",
                "-e",
                "OPENASRPORTAL_HOST=0.0.0.0",
                "-v",
                volume + ":/data",
                args.image,
            )
            info = json.loads(docker("inspect", name))[0]
            port = info["NetworkSettings"]["Ports"]["10087/tcp"][0]["HostPort"]
            base = f"http://127.0.0.1:{port}"
            # Cold Python imports under ARM64 emulation need a larger startup budget.
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    with urlopen(base + "/health", timeout=2) as response:
                        assert json.load(response)["status"] == "ok"
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Container readiness timeout: " + docker("logs", name))
            assert docker("exec", name, "id", "-u") == "10001"

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

            password = "Isolated container admin password 2026!"
            state = api("/v1/admin/auth/status")
            if original is None:
                assert not state["initialized"]
                admin_token = api(
                    "/v1/admin/auth/setup",
                    {
                        "password": password,
                        "confirmPassword": password,
                        "setupChallenge": state["setupChallenge"],
                    },
                )["token"]
                original = api("/v1/admin/asr-keys", {"title": "container-test"}, admin_token)[
                    "key"
                ]
            else:
                assert state["initialized"], "recreating container reset administrator setup"
                admin_token = api("/v1/admin/auth/login", {"password": password})["token"]
            request = Request(
                base + "/v1/profiles",
                headers={"Authorization": "Bearer " + original},
            )
            with urlopen(request) as response:
                assert "profiles" in json.load(response)
            recognition = {"Authorization": "Bearer " + original}
            with urlopen(Request(base + "/v1/hotwords", headers=recognition)) as response:
                vocabulary = json.load(response)
                assert response.headers["Cache-Control"] == "no-store"
            if vocabulary["revision"] == 0:
                update = Request(
                    base + "/v1/hotwords",
                    method="PATCH",
                    headers={
                        **recognition,
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(
                        {
                            "revision": 0,
                            "settings": {
                                "manualTerms": [{"text": "麒麟", "weight": 4}],
                            },
                        }
                    ).encode(),
                )
                with urlopen(update) as response:
                    vocabulary = json.load(response)
            assert vocabulary["settings"]["manualTerms"] == [{"text": "麒麟", "weight": 4}]
            assert vocabulary["settings"]["autoLearn"] is False
            assert vocabulary["settings"]["enabled"] is False
            with urlopen(Request(base + "/v1/hotwords/catalog", headers=recognition)) as response:
                assert any(row["id"] == "tech-ai" for row in json.load(response)["sources"])
            admin = {
                "Authorization": "Bearer " + admin_token,
                "Content-Type": "application/json",
            }
            if public_id is None:
                with urlopen(
                    Request(
                        base + "/v1/admin/hotwords/public-dictionaries",
                        method="POST",
                        headers=admin,
                        data=json.dumps(
                            {"title": "容器公共表测试", "content": "医学成像|4"}
                        ).encode(),
                    )
                ) as response:
                    public_id = json.load(response)["id"]
            with urlopen(
                Request(base + "/v1/hotwords/catalog/" + public_id, headers=recognition)
            ) as response:
                assert json.load(response)["words"][0]["text"] == "医学成像"
            if not vocabulary["dictionaries"]:
                imported = Request(
                    base + "/v1/hotwords/dictionaries",
                    method="POST",
                    headers={**recognition, "Content-Type": "application/json"},
                    data=json.dumps(
                        {"revision": vocabulary["revision"], "sourceId": "tech-ai"}
                    ).encode(),
                )
                with urlopen(imported) as response:
                    vocabulary = json.load(response)
            assert vocabulary["dictionaries"][0]["source"]["id"] == "tech-ai"
            with urlopen(base + "/admin") as response:
                assert b"<html" in response.read().lower()
            for attempt in range(50):
                if docker("inspect", "--format", "{{.State.Health.Status}}", name) == "healthy":
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Container healthcheck failed")
            docker("rm", "-f", name)
        print(
            "PASS Portal container: non-root, HTTP API/admin resources, healthcheck, persistent credentials and personal hotwords"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
