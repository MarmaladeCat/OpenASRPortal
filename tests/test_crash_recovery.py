"""Real process termination and loopback file requests, never a power-loss claim."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from openasrportal.domain.config import LOCAL_FILE_PATH
from openasrportal.entrypoints.service import initialize, write_json

ROOT = Path(__file__).resolve().parents[1]


class CrashRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_kill_before_and_after_file_submission_recovers_without_replay(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="crash-", dir=ROOT / "test-results") as name:
            directory = Path(name)
            config = directory / "service.json"
            initialize(config)
            values = json.loads(config.read_text())
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                values["port"] = sock.getsockname()[1]
            write_json(config, values)
            original_config = config.read_bytes()
            base = f"http://127.0.0.1:{values['port']}"
            submitted, release = asyncio.Event(), asyncio.Event()
            requests = []

            async def recognize(request):
                requests.append(await request.json())
                submitted.set()
                await release.wait()
                return web.json_response({"request_id": str(len(requests)),
                                          "output": {"text": "恢复后的定稿。"}})

            app = web.Application()
            app.router.add_post(LOCAL_FILE_PATH, recognize)
            process = None
            admin, key = "", ""
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
                   "OPENASR_DATA_ROOT": str(directory / "unused-default")}
            async with TestServer(app) as upstream, aiohttp.ClientSession() as client:
                async def api(path, body=None, *, admin_request=False, method=None):
                    async with client.request(
                        method or ("GET" if body is None else "POST"), base + path,
                        json=body, headers={"Authorization": "Bearer " + (admin if admin_request else key)},
                        timeout=aiohttp.ClientTimeout(total=3),
                    ) as response:
                        self.assertLess(response.status, 300, await response.text())
                        return await response.json()

                async def start(iteration):
                    nonlocal process
                    old_ready = (directory / "control/ready.json").read_bytes() if iteration else b""
                    with (directory / f"process-{iteration}.log").open("wb") as log:
                        process = subprocess.Popen(
                            [sys.executable, "-B", "-m", "openasrportal.entrypoints.service",
                             "run", "--config", str(config)], cwd=ROOT, env=env, stdout=log, stderr=log,
                        )
                    deadline = asyncio.get_running_loop().time() + 20
                    while True:
                        self.assertIsNone(process.poll(), "service exited before readiness")
                        try:
                            ready = (directory / "control/ready.json").read_bytes()
                            if ready != old_ready and (await api("/health"))["status"] == "ok":
                                return
                        except (FileNotFoundError, aiohttp.ClientError):
                            pass
                        self.assertLess(asyncio.get_running_loop().time(), deadline)
                        await asyncio.sleep(.05)

                async def session():
                    descriptor = await api("/v1/sessions", {"profileId": "file",
                                           "requiredFeatures": ["effectiveSessionLimits"]})
                    ws = await client.ws_connect(base + descriptor["streamPath"] + "?ticket=" + descriptor["ticket"])
                    self.assertEqual((await ws.receive_json(timeout=3))["type"], "session.ready")
                    return ws, descriptor

                try:
                    await start(0)
                    challenge = (await api("/v1/admin/auth/status"))["setupChallenge"]
                    password = "Disposable crash recovery 2026!"
                    admin = (await api("/v1/admin/auth/setup", {"password": password,
                                 "confirmPassword": password, "setupChallenge": challenge}))["token"]
                    created = await api("/v1/admin/asr-keys", {"title": "crash-test"}, admin_request=True)
                    key = created["key"]
                    await api("/v1/admin/profiles", {
                        "id": "file", "title": "Crash file fixture", "provider": "openlocalasr_file",
                        "configuration": {"apiKey": "fictional", "endpoint": str(upstream.make_url(LOCAL_FILE_PATH))},
                    }, admin_request=True)
                    for iteration, after_submit in enumerate((False, True), 1):
                        ws, descriptor = await session()
                        await ws.send_bytes(bytes(6400))
                        # Public quota observation establishes that the service consumed the PCM.
                        deadline = asyncio.get_running_loop().time() + 3
                        while True:
                            usage = await api("/v1/admin/usage", admin_request=True)
                            if usage["total"]["audioSeconds"] >= iteration * .2 - .00001:
                                break
                            self.assertLess(asyncio.get_running_loop().time(), deadline)
                            await asyncio.sleep(.01)
                        if after_submit:
                            await ws.send_json({"type": "audio.end"})
                            await asyncio.wait_for(submitted.wait(), 3)
                        before = (await api("/v1/admin/usage", admin_request=True))["total"]
                        self.assertEqual(len(requests), int(after_submit))
                        process.kill()  # SIGKILL on Linux, TerminateProcess on Windows.
                        await asyncio.to_thread(process.wait, 5)
                        self.assertNotEqual(process.returncode, 0)
                        self.assertIn((await ws.receive(timeout=3)).type,
                                      (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR))
                        await ws.close()
                        ready = json.loads((directory / "control/ready.json").read_text())
                        (directory / "control" / (ready["instance"] + ".stop")).touch()
                        await start(iteration)
                        self.assertEqual(config.read_bytes(), original_config)
                        admin = (await api("/v1/admin/auth/login", {"password": password}))["token"]
                        self.assertEqual((await api("/v1/profiles"))["profiles"][0]["id"], "file")
                        self.assertEqual((await api("/v1/admin/usage", admin_request=True))["total"], before)
                        self.assertEqual(len(requests), int(after_submit), "restart must not replay abandoned audio")
                        async with client.get(base + descriptor["streamPath"] + "?ticket=" + descriptor["ticket"]) as response:
                            self.assertEqual(response.status, 401)
                    release.set()
                    ws, _ = await session()
                    await ws.send_bytes(bytes(6400))
                    await ws.send_json({"type": "audio.end"})
                    events = []
                    while not events or events[-1]["type"] != "session.finished":
                        events.append(await ws.receive_json(timeout=5))
                        self.assertNotEqual(events[-1]["type"], "session.error")
                    self.assertEqual([e["text"] for e in events if e["type"] == "transcript.final"], ["恢复后的定稿。"])
                    self.assertEqual(events[-1]["finalCount"], 1)
                    self.assertEqual(len(requests), 2)
                    await ws.close()
                finally:
                    release.set()
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        await asyncio.to_thread(process.wait, 5)
