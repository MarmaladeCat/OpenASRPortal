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
    return {"generation": identity, "key": store.reveal_asr_key(identity)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    result = provision(config["dataDir"], args.client_id)
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(config["host"], config["host"])
    host = f"[{host}]" if ":" in host else host
    write_json(
        args.output,
        {
            "schemaVersion": 1,
            "generation": result["generation"],
            "portal": {
                "id": "local-input",
                "name": "本机 Portal",
                "url": f"http://{host}:{config['port']}",
                "apiKey": result["key"],
                "profileId": "",
            },
        },
    )


if __name__ == "__main__":
    main()
