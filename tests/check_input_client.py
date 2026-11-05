"""Opt-in black-box consumer check, with an ephemeral Portal and synthetic ASR.

The consumer is a separate process using only HTTP/WS. All temporary storage is
under this Portal checkout; no microphone, desktop or installed input method.
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from aiohttp.test_utils import TestServer
from support_auth import portal_for_tests as Portal
from test_portal import FakeProvider

from openasrportal.storage.store import Store


async def check(client_dir):
    root = Path(__file__).resolve().parents[1]
    cache = root / "test-results"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="input-contract-", dir=cache) as directory:
        store = Store(directory)
        store.save("local", "Synthetic contract fixture", "openlocalasr", {"apiKey": "fake-key"})
        portal = Portal(store, "client-key", "admin-key", factory=FakeProvider)
        async with TestServer(portal.app()) as server:
            env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(client_dir / "src"),
            }
            process = await asyncio.create_subprocess_exec(
                sys.executable,
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Isolated Portal/Input contract check")
    parser.add_argument("--client-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.client_dir.resolve()))
