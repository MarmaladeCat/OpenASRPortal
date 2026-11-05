"""Database-owned administrator authentication and consent-based local enrollment."""

import hashlib
import secrets
import time

SESSION_SECONDS = 1800
PAIRING_SECONDS = 600


class AuthError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise AuthError("INVALID_PASSWORD", "管理密码须为 12–1024 个字符")
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + value.hex()


def verify_password(password, encoded):
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (
            (algorithm, n, r, p) != ("scrypt", "16384", "8", "1")
            or len(salt) != 32
            or len(expected) != 64
        ):
            return False
        value = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
        )
        return secrets.compare_digest(value, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class AuthStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS admin_credentials ("
                "id INTEGER PRIMARY KEY CHECK(id=1), password_hash TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS admin_sessions ("
                "digest TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS auth_attempts ("
                "scope TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS local_input_bindings ("
                "client_id TEXT PRIMARY KEY, key_id TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS local_input_pairings ("
                "id TEXT PRIMARY KEY, client_id TEXT NOT NULL, claim_digest TEXT NOT NULL, "
                "user_code TEXT UNIQUE NOT NULL, expires_at REAL NOT NULL, key_id TEXT)"
            )

    def initialized(self):
        with self.store.connection() as db:
            return db.execute("SELECT 1 FROM admin_credentials WHERE id=1").fetchone() is not None

    def limit(self, scope, peer):
        now = time.time()
        blocked = False
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_attempts WHERE started_at<?", (now - 120,))
            for name, maximum in ((scope + ":all", 100), (scope + ":" + peer, 10)):
                row = db.execute("SELECT * FROM auth_attempts WHERE scope=?", (name,)).fetchone()
                if row is None or row["started_at"] < now - 60:
                    db.execute("INSERT OR REPLACE INTO auth_attempts VALUES (?,?,1)", (name, now))
                elif row["attempts"] >= maximum:
                    blocked = True
                else:
                    db.execute(
                        "UPDATE auth_attempts SET attempts=attempts+1 WHERE scope=?", (name,)
                    )
        if blocked:
            raise AuthError("AUTH_RATE_LIMITED", "尝试过于频繁，请稍后重试", 429)

    @staticmethod
    def _session(db):
        token = "portal_admin_" + secrets.token_urlsafe(32)
        now = time.time()
        db.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,))
        db.execute(
            "INSERT INTO admin_sessions VALUES (?,?)", (digest(token), now + SESSION_SECONDS)
        )
        return {"token": token, "expiresInMs": SESSION_SECONDS * 1000}

    def issue_session(self):
        """Trusted in-process operation; HTTP callers must use setup/login/tickets."""
        with self.store.connection() as db:
            if not db.execute("SELECT 1 FROM admin_credentials WHERE id=1").fetchone():
                raise AuthError("SETUP_REQUIRED", "请先设置管理密码", 409)
            return self._session(db)

    def setup(self, password, pairing_code=None):
        encoded = password_hash(password)
        if self.store.authorize_asr(password):
            raise AuthError("INVALID_PASSWORD", "管理密码不能使用已有的识别 Key")
        key_id = None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM admin_credentials WHERE id=1").fetchone():
                raise AuthError("ALREADY_INITIALIZED", "管理密码已经设置，请登录", 409)
            if pairing_code:
                key_id = self._approve(db, pairing_code)
            db.execute("INSERT INTO admin_credentials VALUES (1,?)", (encoded,))
            result = self._session(db)
        if key_id:
            self.store.usage.ensure_account("key", key_id)
        return {**result, "localInputApproved": bool(key_id)}

    def login(self, password, peer):
        self.limit("login", peer)
        with self.store.connection() as db:
            row = db.execute("SELECT password_hash FROM admin_credentials WHERE id=1").fetchone()
        if row is None:
            raise AuthError("SETUP_REQUIRED", "请先设置管理密码", 409)
        if not verify_password(password, row[0]):
            raise AuthError("AUTH_FAILED", "管理密码错误", 401)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT password_hash FROM admin_credentials WHERE id=1"
            ).fetchone()
            if not current or current[0] != row[0]:
                raise AuthError("AUTH_FAILED", "管理密码已更新，请重新登录", 401)
            return self._session(db)

    def authorized(self, token):
        if not isinstance(token, str) or not token or len(token) > 512:
            return False
        with self.store.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM admin_sessions WHERE digest=? AND expires_at>?",
                    (digest(token), time.time()),
                ).fetchone()
                is not None
            )

    def logout(self, token):
        with self.store.connection() as db:
            db.execute("DELETE FROM admin_sessions WHERE digest=?", (digest(token),))

    def set_password(self, password):
        """Explicit offline recovery by the database owner; never environment-driven."""
        encoded = password_hash(password)
        if self.store.authorize_asr(password):
            raise AuthError("INVALID_PASSWORD", "管理密码不能使用已有的识别 Key")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO admin_credentials VALUES (1,?)", (encoded,))
            db.execute("DELETE FROM admin_sessions")

    def start_pairing(self, client_id, peer):
        if (
            not isinstance(client_id, str)
            or len(client_id) != 32
            or any(c not in "0123456789abcdef" for c in client_id)
        ):
            raise AuthError("INVALID_CLIENT", "输入法客户端标识无效")
        self.limit("pairing", peer)
        identity, secret = secrets.token_hex(16), secrets.token_urlsafe(32)
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
        now = time.time()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM local_input_pairings WHERE expires_at<=?", (now,))
            db.execute(
                "DELETE FROM local_input_pairings WHERE client_id=? AND key_id IS NULL",
                (client_id,),
            )
            if db.execute("SELECT count(*) FROM local_input_pairings").fetchone()[0] >= 64:
                raise AuthError("PAIRING_BUSY", "配对请求过多，请稍后重试", 429)
            db.execute(
                "INSERT INTO local_input_pairings VALUES (?,?,?,?,?,NULL)",
                (identity, client_id, digest(secret), code, now + PAIRING_SECONDS),
            )
        return {
            "id": identity,
            "claimToken": secret,
            "userCode": code,
            "expiresAt": now + PAIRING_SECONDS,
            "approvalPath": "/admin?pair=" + code,
            "setupRequired": not self.initialized(),
        }

    def pending_pairing(self, code):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT id,user_code,expires_at,key_id,claim_digest FROM local_input_pairings "
                "WHERE user_code=? AND expires_at>?",
                (code, time.time()),
            ).fetchone()
        if row is None:
            raise AuthError(
                "PAIRING_EXPIRED", "输入法配对不存在或已过期，请在输入法中重新发起", 410
            )
        return {
            "id": row["id"],
            "userCode": row["user_code"],
            "expiresAt": row["expires_at"],
            "approved": bool(row["key_id"]),
            "delivered": bool(row["key_id"]) and not bool(row["claim_digest"]),
            "title": "local-input",
        }

    def _approve(self, db, code):
        row = db.execute(
            "SELECT * FROM local_input_pairings WHERE user_code=? AND expires_at>?",
            (code, time.time()),
        ).fetchone()
        if row is None:
            raise AuthError("PAIRING_EXPIRED", "输入法配对不存在或已过期，请重新发起", 410)
        if row["key_id"]:
            return row["key_id"]
        previous = db.execute(
            "SELECT k.id FROM local_input_bindings b JOIN asr_keys k ON k.id=b.key_id "
            "WHERE b.client_id=? AND k.revoked=0",
            (row["client_id"],),
        ).fetchone()
        identity = previous[0] if previous else secrets.token_hex(12)
        if previous is None:
            key = "asr_" + secrets.token_urlsafe(32)
            encrypted = self.store.encrypt_key(key)
            db.execute(
                "INSERT INTO asr_keys (id,title,digest,prefix,created_at,encrypted_secret) "
                "VALUES (?,?,?,?,?,?)",
                (identity, "local-input", digest(key), key[:12], time.time(), encrypted),
            )
            db.execute(
                "INSERT OR REPLACE INTO local_input_bindings VALUES (?,?)",
                (row["client_id"], identity),
            )
        db.execute("UPDATE local_input_pairings SET key_id=? WHERE id=?", (identity, row["id"]))
        return identity

    def approve_pairing(self, code):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            identity = self._approve(db, code)
        self.store.usage.ensure_account("key", identity)
        return {"approved": True, "keyId": identity, "title": "local-input"}

    def claim_pairing(self, identity, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 512:
            raise AuthError("AUTH_FAILED", "输入法配对凭据无效", 401)
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM local_input_pairings WHERE id=?", (identity,)
            ).fetchone()
        if row is None or not secrets.compare_digest(row["claim_digest"], digest(token)):
            raise AuthError("AUTH_FAILED", "输入法配对凭据无效", 401)
        if row["expires_at"] <= time.time():
            raise AuthError("PAIRING_EXPIRED", "输入法配对已过期，请重新发起", 410)
        if not row["key_id"]:
            return {"state": "pending", "setupRequired": not self.initialized()}
        record = self.store.asr_key(row["key_id"])
        if not record or record["revoked"]:
            raise AuthError("KEY_REVOKED", "本机输入法 Key 已撤销，请重新配对并授权", 403)
        return {
            "state": "approved",
            "key": self.store.reveal_asr_key(row["key_id"]),
            "keyId": row["key_id"],
            "title": "local-input",
        }

    def acknowledge_pairing(self, identity, token):
        self.claim_pairing(identity, token)
        with self.store.connection() as db:
            db.execute(
                "UPDATE local_input_pairings SET claim_digest='' WHERE id=? AND key_id IS NOT NULL",
                (identity,),
            )
