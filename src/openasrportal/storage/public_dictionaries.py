"""Administrator-owned recommendation tables shared by all access keys."""

import json
import secrets
import time
from urllib.parse import urlsplit


class PublicDictionaryConflict(ValueError):
    code = "PUBLIC_DICTIONARY_CONFLICT"


def validate_metadata(patch, previous=None):
    result = {
        "title": "",
        "description": "",
        "license": "",
        "homepage": "",
        "enabled": True,
        **(previous or {}),
        **patch,
    }
    for name, limit in (
        ("title", 100),
        ("description", 2000),
        ("license", 500),
        ("homepage", 1000),
    ):
        value = result[name]
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{name} 必须为不超过 {limit} 字符的文本")
        result[name] = value.strip()
    if not result["title"]:
        raise ValueError("请填写公共热词表名称")
    if type(result["enabled"]) is not bool:
        raise ValueError("enabled 必须为布尔值")
    if result["homepage"]:
        url = urlsplit(result["homepage"])
        if url.scheme not in ("http", "https") or not url.netloc:
            raise ValueError("来源网页须为 HTTP/HTTPS 地址")
    return {
        name: result[name] for name in ("title", "description", "license", "homepage", "enabled")
    }


class PublicDictionaryStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS public_hotword_dictionaries "
                "(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,metadata TEXT NOT NULL,"
                "payload TEXT NOT NULL,source TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,"
                "word_count INTEGER NOT NULL,format TEXT NOT NULL)"
            )

    @staticmethod
    def record(row, detail=False):
        metadata = json.loads(row["metadata"])
        source = json.loads(row["source"])
        result = {
            "id": row["id"],
            "revision": row["revision"],
            **metadata,
            "format": row["format"],
            "wordCount": row["word_count"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "source": source,
            "sha256": source.get("sha256", ""),
        }
        if detail:
            result.update(json.loads(row["payload"]))
        return result

    def listing(self, *, published_only=False):
        with self.store.connection() as db:
            records = [
                self.record(row)
                for row in db.execute(
                    "SELECT id,revision,metadata,source,created_at,updated_at,word_count,format "
                    "FROM public_hotword_dictionaries ORDER BY created_at,id"
                )
            ]
        return [row for row in records if row["enabled"]] if published_only else records

    def get(self, identity):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM public_hotword_dictionaries WHERE id=?", (identity,)
            ).fetchone()
        return self.record(row, detail=True) if row else None

    @staticmethod
    def insert(db, identity, metadata, parsed, source):
        now = time.time()
        db.execute(
            "INSERT INTO public_hotword_dictionaries VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identity,
                1,
                json.dumps(validate_metadata(metadata), ensure_ascii=False),
                json.dumps(parsed, ensure_ascii=False),
                json.dumps(source, ensure_ascii=False),
                now,
                now,
                len(parsed["words"]),
                parsed["format"],
            ),
        )

    def seed(self, records):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM settings WHERE name='publicHotwordSeeded'").fetchone():
                return
            for identity, metadata, parsed, source in records:
                self.insert(db, identity, metadata, parsed, source)
            db.execute("INSERT INTO settings VALUES ('publicHotwordSeeded','1')")

    def create(self, metadata, parsed, source):
        identity = "public-" + secrets.token_hex(12)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM public_hotword_dictionaries").fetchone()[0] >= 100:
                raise ValueError("公共热词表最多 100 张，请先删除不需要的表")
            self.insert(db, identity, metadata, parsed, source)
        return self.get(identity)

    def update(self, identity, revision, metadata, parsed=None, source=None, *, delete=False):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM public_hotword_dictionaries WHERE id=?", (identity,)
            ).fetchone()
            if row is None:
                return None
            if type(revision) is not int or revision != row["revision"]:
                raise PublicDictionaryConflict("公共热词表已更新，请刷新后重试")
            if delete:
                db.execute("DELETE FROM public_hotword_dictionaries WHERE id=?", (identity,))
                return {"ok": True}
            updated = validate_metadata(metadata, json.loads(row["metadata"]))
            db.execute(
                "UPDATE public_hotword_dictionaries SET revision=revision+1,metadata=?,"
                "payload=?,source=?,updated_at=?,word_count=?,format=? WHERE id=?",
                (
                    json.dumps(updated, ensure_ascii=False),
                    json.dumps(parsed, ensure_ascii=False)
                    if parsed is not None
                    else row["payload"],
                    json.dumps(source, ensure_ascii=False) if source is not None else row["source"],
                    time.time(),
                    len(parsed["words"]) if parsed is not None else row["word_count"],
                    parsed["format"] if parsed is not None else row["format"],
                    identity,
                ),
            )
        return self.get(identity)
