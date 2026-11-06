"""Offline, database-owner-only provisioning for the unified Windows installer.

No HTTP enrollment, administrator password or secret command-line argument.
The installer protects the output directory with SYSTEM/admin/recipient ACLs.
"""

import argparse
import hashlib
import secrets
import time
from pathlib import Path

from ..storage.store import Store
from .service import load_config, write_json


def provision(directory, client_id):
    if not isinstance(client_id, str) or not client_id or len(client_id) > 256:
        raise ValueError("Invalid installation client identity")
    store = Store(directory)
    binding = "installer-" + hashlib.sha256(client_id.encode()).hexdigest()
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT k.id FROM local_input_bindings b JOIN asr_keys k ON k.id=b.key_id "
            "WHERE b.client_id=? AND k.revoked=0",
            (binding,),
        ).fetchone()
        if row:
            identity = row[0]
        else:
            identity, key = secrets.token_hex(12), "asr_" + secrets.token_urlsafe(32)
            encrypted = store.encrypt_key(key)
            db.execute(
                "INSERT INTO asr_keys (id,title,digest,prefix,created_at,encrypted_secret) VALUES (?,?,?,?,?,?)",
                (
                    identity,
                    "local-input",
                    hashlib.sha256(key.encode()).hexdigest(),
                    key[:12],
                    time.time(),
                    encrypted,
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO local_input_bindings VALUES (?,?)", (binding, identity)
            )
    store.usage.ensure_account("key", identity)
    return {
        "generation": identity,
        "key": store.reveal_asr_key(identity),
        "setupRequired": not store.auth.initialized(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--data-dir", type=Path)
    source.add_argument("--installed", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:10087")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.installed:
        environment = Path("/var/lib/openasr/portal/service.env")
        import shlex

        values = {}
        for line in environment.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith(("#", ";")):
                key, value = line.split("=", 1)
                values[key.strip()] = " ".join(shlex.split(value))
        args.data_dir = Path(values["OPENASRPORTAL_DATA"])
        args.url = (
            Path("/usr/share/openasrportal/admin.url")
            .read_text(encoding="utf-8")
            .strip()
            .removesuffix("/admin")
        )
    if args.config:
        config = load_config(args.config)
    else:
        from urllib.parse import urlsplit

        address = urlsplit(args.url)
        if (
            address.scheme not in {"http", "https"}
            or not address.hostname
            or address.username
            or address.password
        ):
            parser.error("Invalid Portal origin")
        config = {
            "dataDir": str(args.data_dir),
            "host": address.hostname,
            "port": address.port or (443 if address.scheme == "https" else 80),
        }
    result = provision(config["dataDir"], args.client_id)
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(config["host"], config["host"])
    host = f"[{host}]" if ":" in host else host
    write_json(
        args.output,
        {
            "schemaVersion": 1,
            "generation": result["generation"],
            "setupRequired": result["setupRequired"],
            "portal": {
                "id": "local-input",
                "name": "本机 Portal",
                "url": f"http://{host}:{config['port']}" if args.config else args.url.rstrip("/"),
                "apiKey": result["key"],
                "profileId": "",
            },
        },
    )


if __name__ == "__main__":
    main()
