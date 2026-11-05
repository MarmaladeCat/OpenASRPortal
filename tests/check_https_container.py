"""Isolated Docker/NGINX TLS + WSS regression with a deterministic upstream."""

import asyncio
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parents[1]


async def verify(base, context):
    async with ClientSession() as client:
        async with client.get(base + "/health", ssl=context) as response:
            assert response.status == 200
        async with client.get(base + "/admin", ssl=context) as response:
            assert response.status == 200
        async with client.post(
            base + "/v1/admin/auth/login", json={"password": "admin-fixture"}, ssl=context
        ) as response:
            assert response.status == 200, await response.text()
            admin = {"Authorization": "Bearer " + (await response.json())["token"]}
        async with client.post(
            base + "/v1/admin/ui-tickets", headers=admin, ssl=context
        ) as response:
            assert response.status == 200, await response.text()
            ticket = (await response.json())["ticket"]
        async with client.post(
            base + "/v1/admin/ui-session", json={"ticket": ticket}, ssl=context
        ) as response:
            assert response.status == 200, await response.text()
        async with client.post(
            base + "/v1/sessions",
            json={"profileId": "local"},
            headers={"Authorization": "Bearer client-fixture"},
            ssl=context,
        ) as response:
            assert response.status == 201, await response.text()
            session = await response.json()
        async with client.ws_connect(
            base + session["streamPath"] + "?ticket=" + session["ticket"], ssl=context
        ) as ws:
            assert (await ws.receive_json(timeout=10))["type"] == "session.ready"
            assert (await ws.receive_json(timeout=10))["type"] == "transcript.partial"
            await ws.send_bytes(bytes(6400))
            await ws.send_json({"type": "audio.end"})
            assert (await ws.receive_json(timeout=10))["type"] == "transcript.final"
            assert (await ws.receive_json(timeout=10))["type"] == "session.finished"
        return session["ticket"]


def main():
    compose = (
        [shutil.which("docker-compose")]
        if shutil.which("docker-compose")
        else ["docker", "compose"]
    )
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="https-", dir=results) as temp:
        temp = Path(temp)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/create_tls_certificate.py"),
                "--host",
                "localhost",
                "--host",
                "127.0.0.1",
                "--output",
                str(temp / "tls"),
            ],
            check=True,
        )
        config = json.loads(
            subprocess.check_output(
                compose
                + ["-f", str(ROOT / "packaging/compose.https.yaml"), "config", "--format", "json"]
            )
        )
        config.pop("name", None)
        project = "portal-https-test-" + str(os.getpid())
        for volume in config.get("volumes", {}).values():
            volume.pop("name", None)
        for network in config.get("networks", {}).values():
            network.pop("name", None)
        portal = config["services"]["portal"]
        portal["image"] = "openasrportal:https-test"
        portal["command"] = ["python", "/fixtures/serve.py"]
        portal["volumes"].extend(
            [
                {
                    "type": "bind",
                    "source": str(ROOT / "tests"),
                    "target": "/tests",
                    "read_only": True,
                },
                {"type": "bind", "source": str(temp), "target": "/fixtures", "read_only": True},
            ]
        )
        os.chmod(temp, 0o755)
        (temp / "serve.py").write_text(
            "import sys\nsys.path.insert(0, '/tests')\nfrom aiohttp import web\n"
            "from test_portal import FakeProvider\nfrom openasrportal.api.server import Portal\n"
            "from openasrportal.storage.store import Store\nstore = Store('/data')\n"
            "if not store.get('local'): store.save('local', 'TLS fixture', 'openlocalasr', {'apiKey': 'fixture'})\n"
            "store.bootstrap_key('client-fixture')\n"
            "if not store.auth.initialized(): store.auth.setup('admin-fixture')\n"
            "web.run_app(Portal(store, factory=FakeProvider, listen_host='0.0.0.0').app(), host='0.0.0.0', port=10087)\n"
        )
        nginx = config["services"]["nginx"]
        for port in nginx["ports"]:
            port.update(published="0", host_ip="127.0.0.1")
        for volume in nginx["volumes"]:
            if volume["target"] == "/etc/nginx/tls":
                volume["source"] = str(temp / "tls")
        path = temp / "compose.json"
        path.write_text(json.dumps(config))
        command = compose + ["-p", project, "-f", str(path)]
        try:
            subprocess.run(command + ["up", "-d", "--build", "--wait"], check=True)
            address = subprocess.check_output(command + ["port", "nginx", "443"], text=True).strip()
            context = ssl.create_default_context(cafile=str(temp / "tls/server.crt"))
            ticket = asyncio.run(verify("https://" + address, context))
            subprocess.run(command + ["exec", "-T", "nginx", "nginx", "-s", "reload"], check=True)
            subprocess.run(
                command + ["up", "-d", "--force-recreate", "portal", "--wait"], check=True
            )
            asyncio.run(verify("https://" + address, context))
            logs = subprocess.check_output(command + ["logs", "nginx"], text=True)
            assert ticket not in logs
            print(
                "PASS Docker build, certificate verification, HTTPS admin login, WSS finalization, reload and Portal recreation; ticket absent from proxy logs"
            )
        finally:
            subprocess.run(command + ["down", "--volumes"], check=True)


if __name__ == "__main__":
    main()
