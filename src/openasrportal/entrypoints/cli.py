"""Service composition root; all writable paths are independent of installed code."""

import argparse
import os
from pathlib import Path

from aiohttp import web

from ..api.server import Portal
from ..storage.store import Store


def application(args):
    """One composition root for foreground, systemd and Windows service hosts."""
    return Portal(Store(args.data_dir), listen_host=args.host).app()


def main():
    parser = argparse.ArgumentParser(description="OpenASRPortal independent speech service")
    parser.add_argument("--host", default=os.environ.get("OPENASRPORTAL_HOST", "127.0.0.1"))
    parser.add_argument("--ipv6", action="store_true", help="also bind all IPv6 interfaces")
    parser.add_argument(
        "--reset-admin-password",
        action="store_true",
        help="interactive DB-owner password recovery; does not start HTTP",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("OPENASRPORTAL_PORT", "10087"))
    )
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    parser.add_argument(
        "--data-dir", default=os.environ.get("OPENASRPORTAL_DATA", str(data_home / "openasrportal"))
    )
    args = parser.parse_args()
    if args.reset_admin_password:
        from .admin import reset_password

        try:
            reset_password(args.data_dir)
        except ValueError as error:
            parser.error(str(error))
        return
    hosts = list(dict.fromkeys([args.host, "::"])) if args.ipv6 else args.host
    web.run_app(application(args), host=hosts, port=args.port, access_log=None)
