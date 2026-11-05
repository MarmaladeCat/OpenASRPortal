"""Portal 自有配置库；不读取其他应用数据库。"""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from ..domain.config import public_config, validate_config
from ..domain.hotwords import capability
from .auth import AuthStore
from .hotwords import HotwordStore
from .key_vault import KeyVault, VaultError
from .public_dictionaries import PublicDictionaryStore
from .usage import UsageStore


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "portal.db"
        self.vault = KeyVault(directory)
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(id TEXT PRIMARY KEY, title TEXT NOT NULL, provider TEXT NOT NULL, configuration TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS asr_keys ("
                "id TEXT PRIMARY KEY, title TEXT NOT NULL, digest TEXT UNIQUE NOT NULL, "
                "prefix TEXT NOT NULL, created_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(asr_keys)")}
            if "encrypted_secret" not in columns:
                connection.execute("ALTER TABLE asr_keys ADD COLUMN encrypted_secret TEXT")
            first = connection.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO settings VALUES ('defaultProfileId', ?)",
                (first[0] if first else "",),
            )
        os.chmod(self.path, 0o600)
        self.usage = UsageStore(self)
        self.hotwords = HotwordStore(self)
        self.public_dictionaries = PublicDictionaryStore(self)
        self.auth = AuthStore(self)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, profile_id):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return {**dict(row), "configuration": json.loads(row["configuration"])} if row else None

    def save(self, profile_id, title, provider, patch):
        previous = self.get(profile_id)
        configuration = validate_config(
            provider,
            patch,
            previous["configuration"] if previous and previous["provider"] == provider else None,
        )
        quota = self.usage.quota("profile", profile_id)
        if provider != "bailian_qwen_asr" and quota and quota["remainingTokens"] is not None:
            raise ValueError("切换到不提供 Token 用量的上游前，请先清除该配置的 Token 限额")
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO profiles VALUES (?, ?, ?, ?)",
                (profile_id, title, provider, json.dumps(configuration)),
            )
            assigned = connection.execute(
                "UPDATE settings SET value=? WHERE name='defaultProfileId' AND value=''",
                (profile_id,),
            )
            if assigned.rowcount:
                connection.execute(
                    "UPDATE settings SET value='0' WHERE name='defaultAutoUnavailable'"
                )
        self.usage.ensure_account("profile", profile_id)
        with self.connection() as connection:
            account = self.usage.account(connection, "profile", profile_id)
            if not account["enabled"] or self.usage.exhausted(account) or account["token_blocked"]:
                self.usage.rotate(connection, profile_id)
        return self.public(self.get(profile_id), admin=True)

    def delete(self, profile_id):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE usage_accounts SET enabled=0,disabled_reason='deleted' "
                "WHERE scope='profile' AND subject_id=?",
                (profile_id,),
            )
            self.usage.rotate(connection, profile_id)
            connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

    def settings(self):
        with self.connection() as connection:
            settings = {
                "defaultProfileId": connection.execute(
                    "SELECT value FROM settings WHERE name='defaultProfileId'"
                ).fetchone()[0]
            }
        return {**settings, "profileOrder": self.usage.profile_order()}

    def set_default(self, profile_id):
        if not isinstance(profile_id, str) or (profile_id and self.get(profile_id) is None):
            raise ValueError("默认 ASR 配置不存在")
        with self.connection() as connection:
            if profile_id:
                self.usage.check_account(connection, "profile", profile_id)
            connection.execute(
                "UPDATE settings SET value=? WHERE name='defaultProfileId'", (profile_id,)
            )
            connection.execute(
                "INSERT OR REPLACE INTO settings VALUES ('defaultAutoUnavailable','0')"
            )
        return self.settings()

    def bootstrap_key(self, key):
        """Migrate the configured legacy access Key once; revocation survives restart."""
        digest = hashlib.sha256(key.encode()).hexdigest()
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO asr_keys (id,title,digest,prefix,created_at) VALUES (?,?,?,?,?)",
                ("bootstrap-" + digest[:16], "已有识别接入 Key", digest, key[:8], time.time()),
            )
        self.remember_asr_key(key)
        with self.connection() as connection:
            identity = connection.execute(
                "SELECT id FROM asr_keys WHERE digest=?", (digest,)
            ).fetchone()[0]
        self.usage.ensure_account("key", identity)

    def encrypt_key(self, key):
        if not self.vault.path.exists():
            with self.connection() as connection:
                if connection.execute(
                    "SELECT 1 FROM asr_keys WHERE encrypted_secret IS NOT NULL LIMIT 1"
                ).fetchone():
                    raise VaultError(
                        "已有加密 ASR Key，但保管文件缺失；请恢复备份，不自动更换保管密钥"
                    )
        return self.vault.encrypt(key)

    def remember_asr_key(self, key):
        """Recover old hash-only records only from a supplied matching original key."""
        digest = hashlib.sha256(key.encode()).hexdigest()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id,encrypted_secret FROM asr_keys WHERE digest=? AND revoked=0", (digest,)
            ).fetchone()
        if row is None:
            return None
        if row["encrypted_secret"] is None:
            secret = self.encrypt_key(key)
            with self.connection() as connection:
                connection.execute(
                    "UPDATE asr_keys SET encrypted_secret=? WHERE id=?", (secret, row["id"])
                )
        return row["id"]

    def create_asr_key(self, title):
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise ValueError("请填写 1–100 字符的 ASR Key 名称")
        key = "asr_" + secrets.token_urlsafe(32)
        identity = secrets.token_hex(12)
        encrypted = self.encrypt_key(key)
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO asr_keys (id,title,digest,prefix,created_at,encrypted_secret) VALUES (?,?,?,?,?,?)",
                (
                    identity,
                    title.strip(),
                    hashlib.sha256(key.encode()).hexdigest(),
                    key[:12],
                    time.time(),
                    encrypted,
                ),
            )
        self.usage.ensure_account("key", identity)
        return {**self.asr_key(identity), "key": key}

    def public_asr_key(self, row):
        return {
            "id": row["id"],
            "title": row["title"],
            "prefix": row["prefix"],
            "createdAt": row["created_at"],
            "revoked": bool(row["revoked"]),
            "canReveal": bool(row["encrypted_secret"]) and not bool(row["revoked"]),
            "quota": self.usage.quota("key", row["id"]),
        }

    def reveal_asr_key(self, identity):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT encrypted_secret,revoked FROM asr_keys WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise KeyError(identity)
        if row["revoked"]:
            raise ValueError("此 Key 已撤销，不能查看或复制")
        if row["encrypted_secret"] is None:
            raise VaultError("此旧 Key 仅有哈希，无法反解；需要导入原值或派生替代 Key")
        return self.vault.decrypt(row["encrypted_secret"])

    def asr_key(self, identity):
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM asr_keys WHERE id=?", (identity,)).fetchone()
        return self.public_asr_key(row) if row else None

    def asr_key_owner(self, identity):
        with self.connection() as db:
            row = db.execute(
                "SELECT digest,revoked FROM asr_keys WHERE id=?", (identity,)
            ).fetchone()
        return dict(row) if row else None

    def asr_keys(self):
        with self.connection() as connection:
            return [
                self.public_asr_key(row)
                for row in connection.execute("SELECT * FROM asr_keys ORDER BY created_at,id")
            ]

    def authorize_asr(self, key):
        digest = hashlib.sha256(key.encode()).hexdigest()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id FROM asr_keys WHERE digest=? AND revoked=0", (digest,)
            ).fetchone()
        return digest if row else None

    def active_digest(self, digest):
        with self.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM asr_keys WHERE digest=? AND revoked=0", (digest,)
                ).fetchone()
                is not None
            )

    def revoke_asr_key(self, identity):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT digest FROM asr_keys WHERE id=?", (identity,)
            ).fetchone()
            if row:
                connection.execute("UPDATE asr_keys SET revoked=1 WHERE id=?", (identity,))
        return row["digest"] if row else None

    def list(self, *, admin=False):
        ids = self.usage.profile_order()
        return [self.public(self.get(profile_id), admin=admin) for profile_id in ids]

    def public(self, profile, *, admin=False):
        streaming = profile["provider"] == "doubao_realtime"
        quota = self.usage.quota("profile", profile["id"])
        if quota is not None and not admin:
            quota = {
                field: quota[field]
                for field in ("enabled", "disabledReason", "exhausted", "tokenBlocked")
            }
        return {
            "id": profile["id"],
            "title": profile["title"],
            "provider": profile["provider"],
            "configuration": public_config(profile["configuration"], profile["provider"]),
            "quota": quota,
            "capabilities": {
                "partialResults": True,
                "textProcessing": "native",
                "latencyClass": "streaming" if streaming else "segmented",
                "audio": {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1},
                "tokenUsage": profile["provider"] == "bailian_qwen_asr",
                "hotwords": capability(profile["provider"]),
            },
        }
