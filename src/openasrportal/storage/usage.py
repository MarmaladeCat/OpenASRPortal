"""Durable audio/token accounting, atomic balances, and ordered upstream rotation."""

import math
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain.asr_protocol import ProviderError
from ..domain.config import BAILIAN_MODEL

BYTES_PER_SECOND = 32000
MAX_INTEGER = 2**63 - 1


class UsageError(ProviderError):
    def __init__(self, code, message, status=402):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def seconds_bytes(value):
    if value is None:
        return None
    if type(value) not in (int, float) or value < 0 or value > MAX_INTEGER / BYTES_PER_SECOND:
        raise ValueError("剩余时长必须为可保存的非负秒数，或 null（不限额）")
    if not math.isfinite(value):
        raise ValueError("剩余时长必须为非负秒数，或 null（不限额）")
    result = math.floor(value * BYTES_PER_SECOND / 2) * 2
    if result > MAX_INTEGER:
        raise ValueError("剩余时长超出可保存范围")
    return result


def token_count(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_INTEGER):
        raise ValueError("剩余 Token 必须为非负整数，或 null（不限额）")
    return value


def reported_tokens(payload):
    """Use real upstream usage only. Never infer tokens from transcript length."""
    if not isinstance(payload, dict):
        return None
    usage = None
    current = payload
    for _ in range(3):
        usage = current.get("usage")
        if isinstance(usage, dict):
            break
        current = current.get("output")
        if not isinstance(current, dict):
            break
    if not isinstance(usage, dict):
        return None

    def number(*names):
        for name in names:
            value = usage.get(name)
            if type(value) is int and 0 <= value <= MAX_INTEGER:
                return value
        return None

    incoming = number("input_tokens", "prompt_tokens", "inputTokens")
    outgoing = number("output_tokens", "completion_tokens", "outputTokens")
    total = number("total_tokens", "totalTokens")
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    if total is None or total > MAX_INTEGER:
        return None
    return {"total": total, "input": incoming, "output": outgoing}


def supports_tokens(profile):
    return profile["provider"] == BAILIAN_MODEL


class UsageStore:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.initialize()

    def initialize(self):
        with self.store.connection() as db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS usage_accounts ("
                "scope TEXT NOT NULL, subject_id TEXT NOT NULL, "
                "remaining_audio_bytes INTEGER, remaining_tokens INTEGER, "
                "enabled INTEGER NOT NULL DEFAULT 1, disabled_reason TEXT NOT NULL DEFAULT '', "
                "token_blocked INTEGER NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 0, "
                "used_audio_bytes INTEGER NOT NULL DEFAULT 0, used_tokens INTEGER NOT NULL DEFAULT 0, "
                "requests INTEGER NOT NULL DEFAULT 0, token_reports INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(scope,subject_id));"
                "CREATE TABLE IF NOT EXISTS usage_sessions ("
                "id TEXT PRIMARY KEY, key_id TEXT, profile_id TEXT NOT NULL, "
                "created_at REAL NOT NULL, started_at REAL, ended_at REAL, state TEXT NOT NULL, "
                "error_code TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL, "
                "reserved_audio_bytes INTEGER NOT NULL DEFAULT 0);"
                "CREATE TABLE IF NOT EXISTS usage_events ("
                "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, at REAL NOT NULL, "
                "key_id TEXT, profile_id TEXT NOT NULL, key_audio_bytes INTEGER NOT NULL DEFAULT 0, "
                "upstream_audio_bytes INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, "
                "tokens INTEGER, input_tokens INTEGER, output_tokens INTEGER, "
                "settled INTEGER NOT NULL DEFAULT 1);"
                "CREATE INDEX IF NOT EXISTS usage_events_time ON usage_events(at);"
                "CREATE INDEX IF NOT EXISTS usage_events_key_time ON usage_events(key_id,at);"
                "CREATE INDEX IF NOT EXISTS usage_events_profile_time ON usage_events(profile_id,at);"
                "CREATE TABLE IF NOT EXISTS usage_metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);"
            )
            db.execute(
                "INSERT OR IGNORE INTO usage_metadata VALUES ('startedAt',?)", (str(self.clock()),)
            )
            db.execute("INSERT OR IGNORE INTO settings VALUES ('defaultAutoUnavailable','0')")
            for position, row in enumerate(db.execute("SELECT id FROM profiles ORDER BY id")):
                db.execute(
                    "INSERT OR IGNORE INTO usage_accounts(scope,subject_id,priority) VALUES ('profile',?,?)",
                    (row[0], position),
                )
            for row in db.execute("SELECT id FROM asr_keys"):
                db.execute(
                    "INSERT OR IGNORE INTO usage_accounts(scope,subject_id) VALUES ('key',?)",
                    (row[0],),
                )

    def ensure_account(self, scope, identity):
        with self.store.connection() as db:
            priority = db.execute(
                "SELECT COALESCE(MAX(priority),-1)+1 FROM usage_accounts WHERE scope='profile'"
            ).fetchone()[0]
            db.execute(
                "INSERT OR IGNORE INTO usage_accounts(scope,subject_id,priority) VALUES (?,?,?)",
                (scope, identity, priority if scope == "profile" else 0),
            )

    @staticmethod
    def account(db, scope, identity):
        return db.execute(
            "SELECT * FROM usage_accounts WHERE scope=? AND subject_id=?", (scope, identity)
        ).fetchone()

    @staticmethod
    def exhausted(account):
        return account["remaining_audio_bytes"] == 0 or account["remaining_tokens"] == 0

    def check_account(self, db, scope, identity):
        account = self.account(db, scope, identity)
        if account is None:
            raise UsageError("ACCOUNT_NOT_FOUND", "计量账户不存在", 404)
        if account["token_blocked"]:
            raise UsageError(
                "TOKEN_USAGE_UNAVAILABLE",
                "上游未返回可计量的 Token；请管理员改用时长限额或调整配额",
                409,
            )
        if self.exhausted(account):
            label = "客户端 Key" if scope == "key" else "上游 ASR"
            raise UsageError("QUOTA_EXHAUSTED", label + "的剩余额度已用尽，请管理员补充额度")
        if not account["enabled"]:
            raise UsageError(
                "PROFILE_DISABLED", "指定上游 ASR 已停用，请选择其他配置或跟随默认", 409
            )
        return account

    def check(self, owner, profile):
        with self.store.connection() as db:
            key = db.execute(
                "SELECT id FROM asr_keys WHERE digest=? AND revoked=0", (owner,)
            ).fetchone()
            if key is None:
                raise UsageError("AUTH_FAILED", "Portal 接入凭据无效", 401)
            key_account = self.check_account(db, "key", key[0])
            profile_account = self.check_account(db, "profile", profile["id"])
            if (
                key_account["remaining_tokens"] is not None
                or profile_account["remaining_tokens"] is not None
            ) and not supports_tokens(profile):
                raise UsageError(
                    "TOKEN_USAGE_UNSUPPORTED",
                    "此上游不提供 Token 用量；请改用时长限额或选择支持 Token 的上游",
                    409,
                )
            return key[0]

    def profile_order(self):
        with self.store.connection() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT p.id FROM profiles p JOIN usage_accounts a ON a.scope='profile' "
                    "AND a.subject_id=p.id ORDER BY a.priority,p.id"
                )
            ]

    def set_order(self, identities):
        if not isinstance(identities, list) or any(
            not isinstance(item, str) for item in identities
        ):
            raise ValueError("上游顺序必须为配置 ID 数组")
        if len(identities) != len(set(identities)) or set(identities) != set(self.profile_order()):
            raise ValueError("上游顺序必须包含全部现有配置，且不能重复")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for position, identity in enumerate(identities):
                db.execute(
                    "UPDATE usage_accounts SET priority=? WHERE scope='profile' AND subject_id=?",
                    (position, identity),
                )

    def configure_defaults(self, patch):
        """Validate all requested changes before mutating ordering/default settings."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if "profileOrder" in patch:
                order = patch["profileOrder"]
                existing = {row[0] for row in db.execute("SELECT id FROM profiles")}
                if (
                    not isinstance(order, list)
                    or any(not isinstance(item, str) for item in order)
                    or len(order) != len(set(order))
                    or set(order) != existing
                ):
                    raise ValueError("上游顺序必须包含全部现有配置，且不能重复")
            if "defaultProfileId" in patch:
                identity = patch["defaultProfileId"]
                if not isinstance(identity, str) or (
                    identity
                    and db.execute("SELECT 1 FROM profiles WHERE id=?", (identity,)).fetchone()
                    is None
                ):
                    raise ValueError("默认 ASR 配置不存在")
                if identity:
                    self.check_account(db, "profile", identity)
            if "profileOrder" in patch:
                for position, identity in enumerate(patch["profileOrder"]):
                    db.execute(
                        "UPDATE usage_accounts SET priority=? WHERE scope='profile' AND subject_id=?",
                        (position, identity),
                    )
            if "defaultProfileId" in patch:
                db.execute(
                    "UPDATE settings SET value=? WHERE name='defaultProfileId'",
                    (patch["defaultProfileId"],),
                )
                db.execute("UPDATE settings SET value='0' WHERE name='defaultAutoUnavailable'")

    def rotate(self, db, current):
        default = db.execute("SELECT value FROM settings WHERE name='defaultProfileId'").fetchone()[
            0
        ]
        if default != current:
            return
        rows = list(
            db.execute(
                "SELECT p.id,a.* FROM profiles p JOIN usage_accounts a ON a.scope='profile' "
                "AND a.subject_id=p.id ORDER BY a.priority,p.id"
            )
        )
        ids = [row["id"] for row in rows]
        start = ids.index(current) + 1 if current in ids else 0
        ordered = rows[start:] + rows[:start]
        next_id = next(
            (
                row["id"]
                for row in ordered
                if row["enabled"] and not row["token_blocked"] and not self.exhausted(row)
            ),
            "",
        )
        db.execute("UPDATE settings SET value=? WHERE name='defaultProfileId'", (next_id,))
        db.execute(
            "UPDATE settings SET value=? WHERE name='defaultAutoUnavailable'",
            ("0" if next_id else "1",),
        )

    def disable_depleted(self, db, profile_id):
        account = self.account(db, "profile", profile_id)
        if account and (self.exhausted(account) or account["token_blocked"]):
            reason = "token_usage_unavailable" if account["token_blocked"] else "quota"
            if account["disabled_reason"] == "manual":
                reason = "manual"
            db.execute(
                "UPDATE usage_accounts SET enabled=0,disabled_reason=? WHERE scope='profile' AND subject_id=?",
                (reason, profile_id),
            )
            self.rotate(db, profile_id)

    def quota(self, scope, identity):
        with self.store.connection() as db:
            account = self.account(db, scope, identity)
            if account is None:
                return None
            reserved = 0
            if scope == "profile":
                reserved = db.execute(
                    "SELECT COALESCE(SUM(reserved_audio_bytes),0) FROM usage_sessions "
                    "WHERE profile_id=? AND ended_at IS NULL",
                    (identity,),
                ).fetchone()[0]
            remaining = account["remaining_audio_bytes"]
            return {
                "remainingSeconds": None if remaining is None else remaining / BYTES_PER_SECOND,
                "remainingTokens": account["remaining_tokens"],
                "reservedSeconds": reserved / BYTES_PER_SECOND,
                "availableSeconds": None
                if remaining is None
                else max(0, remaining - reserved) / BYTES_PER_SECOND,
                "enabled": bool(account["enabled"]),
                "disabledReason": account["disabled_reason"],
                "tokenBlocked": bool(account["token_blocked"]),
                "exhausted": self.exhausted(account),
                "priority": account["priority"],
                "usedSeconds": account["used_audio_bytes"] / BYTES_PER_SECOND,
                "reportedTokens": account["used_tokens"],
                "tokens": None
                if account["requests"] and not account["token_reports"]
                else account["used_tokens"],
                "requests": account["requests"],
                "tokenReports": account["token_reports"],
                "unreportedRequests": account["requests"] - account["token_reports"],
            }

    def update_quota(self, scope, identity, patch):
        permitted = {"remainingSeconds", "remainingTokens"} | (
            {"enabled"} if scope == "profile" else set()
        )
        if not isinstance(patch, dict) or not patch or patch.keys() - permitted:
            raise ValueError("未知的配额字段，请填写剩余秒数、剩余 Token 或上游启用状态")
        if "enabled" in patch and type(patch["enabled"]) is not bool:
            raise ValueError("上游启用状态必须为布尔值")
        profile = self.store.get(identity) if scope == "profile" else None
        if (
            patch.get("remainingTokens") is not None
            and scope == "profile"
            and not supports_tokens(profile)
        ):
            raise ValueError("此上游不提供 Token 用量，请使用时长限额")
        updates = {}
        if "remainingSeconds" in patch:
            updates["remaining_audio_bytes"] = seconds_bytes(patch["remainingSeconds"])
        if "remainingTokens" in patch:
            updates["remaining_tokens"] = token_count(patch["remainingTokens"])
            updates["token_blocked"] = 0
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            account = self.account(db, scope, identity)
            if account is None:
                raise UsageError("ACCOUNT_NOT_FOUND", "计量账户不存在", 404)
            if "enabled" in patch:
                updates["enabled"] = int(patch["enabled"])
                updates["disabled_reason"] = "" if patch["enabled"] else "manual"
            elif scope == "profile" and account["disabled_reason"] in (
                "quota",
                "token_usage_unavailable",
            ):
                updates["enabled"] = 1
                updates["disabled_reason"] = ""
            for field, value in updates.items():
                db.execute(
                    f"UPDATE usage_accounts SET {field}=? WHERE scope=? AND subject_id=?",
                    (value, scope, identity),
                )
            if scope == "profile":
                self.disable_depleted(db, identity)
                if not self.account(db, scope, identity)["enabled"]:
                    self.rotate(db, identity)
                elif (
                    db.execute(
                        "SELECT value FROM settings WHERE name='defaultAutoUnavailable'"
                    ).fetchone()[0]
                    == "1"
                ):
                    eligible = next(
                        (
                            row[0]
                            for row in db.execute(
                                "SELECT p.id FROM profiles p JOIN usage_accounts a ON a.scope='profile' "
                                "AND a.subject_id=p.id WHERE a.enabled=1 AND a.token_blocked=0 "
                                "AND (a.remaining_audio_bytes IS NULL OR a.remaining_audio_bytes>0) "
                                "AND (a.remaining_tokens IS NULL OR a.remaining_tokens>0) ORDER BY a.priority,p.id"
                            )
                        ),
                        "",
                    )
                    if eligible:
                        db.execute(
                            "UPDATE settings SET value=? WHERE name='defaultProfileId'", (eligible,)
                        )
                        db.execute(
                            "UPDATE settings SET value='0' WHERE name='defaultAutoUnavailable'"
                        )
        return self.quota(scope, identity)

    def new_session(self, identity, owner, profile_id, purpose="dictation"):
        with self.store.connection() as db:
            key_id = None
            if owner:
                row = db.execute("SELECT id FROM asr_keys WHERE digest=?", (owner,)).fetchone()
                key_id = row[0] if row else None
            db.execute(
                "INSERT OR IGNORE INTO usage_sessions(id,key_id,profile_id,created_at,state,purpose) "
                "VALUES (?,?,?,?, 'pending',?)",
                (identity, key_id, profile_id, self.clock(), purpose),
            )

    def activate(self, identity):
        with self.store.connection() as db:
            db.execute(
                "UPDATE usage_sessions SET started_at=?,state='active' WHERE id=? AND ended_at IS NULL",
                (self.clock(), identity),
            )

    def event(self, db, session, *, key_audio=0, upstream_audio=0, requests=0, settled=1):
        if not requests:
            minute = int(self.clock() // 60) * 60
            identity = f"audio:{session['id']}:{minute}"
            db.execute(
                "INSERT INTO usage_events(id,session_id,at,key_id,profile_id,key_audio_bytes,"
                "upstream_audio_bytes) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "key_audio_bytes=key_audio_bytes+excluded.key_audio_bytes,"
                "upstream_audio_bytes=upstream_audio_bytes+excluded.upstream_audio_bytes",
                (
                    identity,
                    session["id"],
                    minute,
                    session["key_id"],
                    session["profile_id"],
                    key_audio,
                    upstream_audio,
                ),
            )
            return identity
        identity = secrets.token_hex(16)
        db.execute(
            "INSERT INTO usage_events(id,session_id,at,key_id,profile_id,key_audio_bytes,"
            "upstream_audio_bytes,requests,settled) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identity,
                session["id"],
                self.clock(),
                session["key_id"],
                session["profile_id"],
                key_audio,
                upstream_audio,
                requests,
                settled,
            ),
        )
        return identity

    @staticmethod
    def session(db, identity):
        row = db.execute("SELECT * FROM usage_sessions WHERE id=?", (identity,)).fetchone()
        if row is None or row["ended_at"] is not None:
            raise UsageError("SESSION_CLOSED", "计量会话已经结束", 409)
        return row

    def accept_audio(self, identity, byte_count):
        """Atomically debit accepted PCM once for both client and upstream."""
        if type(byte_count) is not int or byte_count < 0 or byte_count % 2:
            raise ValueError("计量音频必须包含完整 PCM16 样本")
        if not byte_count:
            return 0, None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self.session(db, identity)
            key = self.check_account(db, "key", session["key_id"]) if session["key_id"] else None
            profile = self.check_account(db, "profile", session["profile_id"])
            available = byte_count
            exhausted_scope = None
            for scope, account in (("key", key), ("profile", profile)):
                if account is None or account["remaining_audio_bytes"] is None:
                    continue
                remaining = account["remaining_audio_bytes"]
                if remaining <= available:
                    available = max(0, remaining // 2 * 2)
                    exhausted_scope = scope
            if key:
                db.execute(
                    "UPDATE usage_accounts SET used_audio_bytes=used_audio_bytes+?, "
                    "remaining_audio_bytes=CASE WHEN remaining_audio_bytes IS NULL THEN NULL "
                    "ELSE MAX(0,remaining_audio_bytes-?) END WHERE scope='key' AND subject_id=?",
                    (available, available, session["key_id"]),
                )
            db.execute(
                "UPDATE usage_accounts SET used_audio_bytes=used_audio_bytes+?, "
                "remaining_audio_bytes=CASE WHEN remaining_audio_bytes IS NULL THEN NULL "
                "ELSE MAX(0,remaining_audio_bytes-?) END WHERE scope='profile' AND subject_id=?",
                (available, available, session["profile_id"]),
            )
            self.disable_depleted(db, session["profile_id"])
            if available:
                self.event(
                    db, session, key_audio=available if key else 0, upstream_audio=available
                )
            return available, exhausted_scope

    def begin_call(self, identity, *, tokens=False):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self.session(db, identity)
            self.check_account(db, "profile", session["profile_id"])
            if session["key_id"]:
                # Audio reaching its exact limit may still be finalized and billed.
                key = self.account(db, "key", session["key_id"])
                if key["remaining_tokens"] == 0 or key["token_blocked"]:
                    raise UsageError("QUOTA_EXHAUSTED", "客户端 Key 的 Token 额度不可继续使用")
            for scope, subject in (("profile", session["profile_id"]), ("key", session["key_id"])):
                if subject:
                    db.execute(
                        "UPDATE usage_accounts SET requests=requests+1 WHERE scope=? AND subject_id=?",
                        (scope, subject),
                    )
            self.disable_depleted(db, session["profile_id"])
            return self.event(
                db,
                session,
                requests=1,
                settled=0 if tokens else 1,
            )

    def complete_call(self, identity, usage, *, final=True):
        unavailable = False
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute("SELECT * FROM usage_events WHERE id=?", (identity,)).fetchone()
            if event is None or event["settled"]:
                return
            old = event["tokens"]
            total = max(old or 0, usage["total"]) if usage else old
            delta = (total or 0) - (old or 0)
            db.execute(
                "UPDATE usage_events SET tokens=?,input_tokens=?,output_tokens=?,settled=? WHERE id=?",
                (
                    total,
                    usage["input"] if usage else event["input_tokens"],
                    usage["output"] if usage else event["output_tokens"],
                    int(final),
                    identity,
                ),
            )
            for scope, subject in (("profile", event["profile_id"]), ("key", event["key_id"])):
                if not subject:
                    continue
                account = self.account(db, scope, subject)
                if usage is not None:
                    db.execute(
                        "UPDATE usage_accounts SET used_tokens=used_tokens+?,token_reports=token_reports+?, "
                        "remaining_tokens=CASE WHEN remaining_tokens IS NULL THEN NULL "
                        "ELSE MAX(0,remaining_tokens-?) END WHERE scope=? AND subject_id=?",
                        (delta, int(old is None), delta, scope, subject),
                    )
                elif final and account["remaining_tokens"] is not None:
                    db.execute(
                        "UPDATE usage_accounts SET token_blocked=1 WHERE scope=? AND subject_id=?",
                        (scope, subject),
                    )
                    unavailable = True
            self.disable_depleted(db, event["profile_id"])
        if unavailable:
            raise UsageError(
                "TOKEN_USAGE_UNAVAILABLE",
                "上游没有返回 Token 用量，已停止 Token 限额会话；请改用时长限额",
                409,
            )

    def finish(self, identity, state, error_code=""):
        with self.store.connection() as db:
            pending = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM usage_events WHERE session_id=? AND settled=0", (identity,)
                )
            ]
        for event in pending:
            try:
                self.complete_call(event, None)
            except UsageError:
                pass  # Preserve the original cancellation/error; balances remain blocked.
        with self.store.connection() as db:
            db.execute(
                "UPDATE usage_sessions SET ended_at=?,state=?,error_code=?,reserved_audio_bytes=0 "
                "WHERE id=? AND ended_at IS NULL",
                (self.clock(), state, error_code, identity),
            )

    def recover(self):
        with self.store.connection() as db:
            sessions = [
                row[0] for row in db.execute("SELECT id FROM usage_sessions WHERE ended_at IS NULL")
            ]
        for identity in sessions:
            self.finish(identity, "interrupted", "SERVICE_RESTARTED")

    def statistics(
        self, start, end, bucket="day", key_id=None, profile_id=None, timezone_name="UTC"
    ):
        if bucket not in ("hour", "day", "month"):
            raise ValueError("统计分组应为 hour / day / month")
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("统计时区无效") from None
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
            raise ValueError("统计开始时间必须早于结束时间")
        start = math.floor(start / 60) * 60
        end = math.ceil(end / 60) * 60
        clauses, parameters = ["at>=?", "at<?"], [start, end]
        if key_id:
            clauses.append("key_id=?")
            parameters.append(key_id)
        if profile_id:
            clauses.append("profile_id=?")
            parameters.append(profile_id)
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT CAST(at/60 AS INTEGER)*60 AS minute,key_id,profile_id,"
                "SUM(key_audio_bytes) AS audio,SUM(upstream_audio_bytes) AS upstream,"
                "SUM(COALESCE(tokens,0)) AS tokens,SUM(requests) AS requests,"
                "SUM(CASE WHEN tokens IS NOT NULL THEN 1 ELSE 0 END) AS reports "
                "FROM usage_events WHERE "
                + " AND ".join(clauses)
                + " GROUP BY minute,key_id,profile_id ORDER BY minute",
                parameters,
            ).fetchall()
            since = float(
                db.execute("SELECT value FROM usage_metadata WHERE name='startedAt'").fetchone()[0]
            )
        total, timeline, keys, profiles = self.empty_total(), {}, {}, {}
        for row in rows:
            moment = datetime.fromtimestamp(row["minute"], zone)
            if bucket == "month":
                moment = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif bucket == "day":
                moment = moment.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                moment = moment.replace(minute=0, second=0, microsecond=0)
            stamp = moment.isoformat()
            for target in (
                total,
                timeline.setdefault(stamp, self.empty_total()),
                profiles.setdefault(row["profile_id"], self.empty_total()),
            ):
                self.add_total(target, row)
            if row["key_id"]:
                self.add_total(keys.setdefault(row["key_id"], self.empty_total()), row)
        return {
            "from": start,
            "to": end,
            "bucket": bucket,
            "timezone": timezone_name,
            "resolutionSeconds": 60,
            "trackingStartedAt": since,
            "total": self.public_total(total),
            "timeline": [
                {"start": stamp, **self.public_total(value)}
                for stamp, value in sorted(timeline.items())
            ],
            "keys": [
                {"id": identity, **self.public_total(value)} for identity, value in keys.items()
            ],
            "profiles": [
                {"id": identity, **self.public_total(value)} for identity, value in profiles.items()
            ],
        }

    @staticmethod
    def empty_total():
        return {"audio": 0, "upstream": 0, "tokens": 0, "requests": 0, "reports": 0}

    @staticmethod
    def add_total(total, row):
        for field in total:
            total[field] += row[field]

    @staticmethod
    def public_total(value):
        return {
            "audioSeconds": value["audio"] / BYTES_PER_SECOND,
            "upstreamAudioSeconds": value["upstream"] / BYTES_PER_SECOND,
            "reportedTokens": value["tokens"],
            "tokens": None if value["requests"] and not value["reports"] else value["tokens"],
            "requests": value["requests"],
            "tokenReports": value["reports"],
            "unreportedRequests": value["requests"] - value["reports"],
        }
