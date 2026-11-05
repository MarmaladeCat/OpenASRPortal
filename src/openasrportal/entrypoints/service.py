"""Portable service lifecycle; OS service registration belongs to packaging only.

The private stop mailbox needs no HTTP endpoint, platform signal or PID killing.
Its directory must be writable only by administrators and the service identity.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import time
import uuid
from pathlib import Path

from aiohttp import web

from .cli import application

LOG = logging.getLogger(__name__)


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
        ) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise ValueError("Service configuration requires schemaVersion 1")
    host, port = config.get("host"), config.get("port")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Service host must not be empty")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Service port must be between 1 and 65535")
    if not isinstance(config.get("dataDir"), str) or not config["dataDir"].strip():
        raise ValueError("Service dataDir must not be empty")
    data = Path(config["dataDir"])
    config["dataDir"] = str(data if data.is_absolute() else path.parent / data)
    return config


def initialize(path):
    """Installation paths only. All administrator/client credentials belong to DB."""
    if not path.exists():
        values = {
            "schemaVersion": 1,
            "host": "127.0.0.1",
            "port": 10087,
            "dataDir": "data",
        }
        # Never replace existing credentials, including concurrently created ones.
        try:
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
            ) as stream:
                json.dump(values, stream, indent=2)
                stream.write("\n")
        except FileExistsError:
            pass
    load_config(path)
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if "apiKey" in values or "adminKey" in values:
        values.pop("apiKey", None)
        values.pop("adminKey", None)
        write_json(path, values)


def control_directory(path):
    return path.parent / "control"


def initialize_foreground(path):
    """Explicit user-local mode; never changes the machine service's state."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    initialize(path)


async def serve(path):
    config = load_config(path)
    args = argparse.Namespace(data_dir=config["dataDir"], host=config["host"])
    control = control_directory(path)
    control.mkdir(exist_ok=True)
    identity = uuid.uuid4().hex
    ready = control / "ready.json"
    stop = control / (identity + ".stop")
    runner = web.AppRunner(application(args), access_log=None, shutdown_timeout=10)
    await runner.setup()
    try:
        await web.TCPSite(runner, config["host"], config["port"]).start()
        write_json(ready, {"instance": identity})
        LOG.info("Portal service ready on %s:%s", config["host"], config["port"])
        while not stop.exists():
            await asyncio.sleep(0.1)
    finally:
        await runner.cleanup()
        stop.unlink(missing_ok=True)
        if (
            ready.exists()
            and json.loads(ready.read_text(encoding="utf-8")).get("instance") == identity
        ):
            ready.unlink(missing_ok=True)
        LOG.info("Portal service stopped")


def request_stop(path, timeout=20):
    ready = control_directory(path) / "ready.json"
    try:
        identity = json.loads(ready.read_text(encoding="utf-8"))["instance"]
    except FileNotFoundError:
        return
    if (
        not isinstance(identity, str)
        or len(identity) != 32
        or any(c not in "0123456789abcdef" for c in identity)
    ):
        raise ValueError("Invalid service instance identity")
    stop = ready.parent / (identity + ".stop")
    stop.touch(mode=0o600, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            if json.loads(ready.read_text(encoding="utf-8")).get("instance") != identity:
                break  # A new instance must never be stopped by this request.
        except FileNotFoundError:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Portal did not finish graceful shutdown")
        time.sleep(0.1)
    stop.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "run", "stop", "foreground"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    path = args.config.resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action == "initialize":
        initialize(path)
    elif args.action == "stop":
        request_stop(path)
    else:
        if args.action == "foreground":
            # Optional MSI foreground mode uses this user's private state. It
            # never reads machine-service credentials or needs administrator rights.
            initialize_foreground(path)
        # SIGTERM uses the same aiohttp cleanup as Ctrl+C; SCM uses the mailbox.
        previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            asyncio.run(serve(path))
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
