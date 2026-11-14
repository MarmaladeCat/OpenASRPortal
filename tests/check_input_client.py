"""Opt-in black-box consumer check, with an ephemeral Portal and synthetic ASR.

The consumer is a separate process using only HTTP/WS. All temporary storage is
under this Portal checkout; no microphone, desktop or installed input method.
"""

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests as Portal
from support_workflows import WorkflowPeers
from test_portal import FakeProvider

from openasrportal.providers.registry import definition
from openasrportal.storage.store import Store


class ContractProvider(FakeProvider):
    # This end-to-end fixture includes cold Jieba initialization and real SQLite
    # commits. Use the profile's real budget; FakeProvider's one-second timeout
    # exists to make isolated timeout unit tests fast, not as a service contract.
    finish_timeout = definition("openlocalasr").factory.finish_timeout


async def check(client_dir, client_python):
    root = Path(__file__).resolve().parents[1]
    cache = root / "test-results"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="input-contract-", dir=cache) as directory:
        store = Store(directory)
        store.save("local", "Synthetic contract fixture", "openlocalasr", {"apiKey": "fake-key"})
        peers = WorkflowPeers()
        peers.configure(store)
        store.set_default("local")
        portal = Portal(store, "client-key", "admin-key", factory=lambda profile:
                        peers.provider(profile) if profile["id"].startswith("workflow-") else ContractProvider(profile))
        async with peers.server, TestServer(portal.app()) as server:
            env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(client_dir / "src"),
            }
            process = await asyncio.create_subprocess_exec(
                str(client_python),
                str(client_dir / "tests" / "portal_contract_probe.py"),
                "--url",
                str(server.make_url("/")).rstrip("/"),
                cwd=client_dir,
                env=env,
            )
            try:
                code = await asyncio.wait_for(process.wait(), 30)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if code:
                raise RuntimeError(f"OpenASRInput contract probe failed ({code})")
            peers.verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Isolated Portal/Input contract check")
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--client-python", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.client_dir.resolve(), args.client_python.absolute()))
