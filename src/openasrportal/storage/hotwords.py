"""Per-access-key rolling word counts. Never persist full transcripts or audio."""

import json
import secrets
import time
from collections import Counter

from ..domain.dictionaries import MAX_DICTIONARIES
from ..domain.hotwords import DEFAULTS, extract_terms, select_terms, validate_settings


class HotwordConflict(ValueError):
    pass


class HotwordStore:
    def __init__(self, store):
        self.store = store
        import jieba

        self.tokenizer = jieba.Tokenizer()
        self.tokenizer.tmp_dir = str(store.path.parent)
        self.tokenizer.cache_file = "jieba.cache"
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hotword_settings "
                "(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, settings TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS hotword_counts "
                "(owner TEXT, day INTEGER, text TEXT, frequency INTEGER, last_seen REAL, "
                "PRIMARY KEY(owner,day,text))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS hotword_finals "
                "(owner TEXT, utterance TEXT, day INTEGER, PRIMARY KEY(owner,utterance))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS hotword_counts_day ON hotword_counts(day)")
            db.execute("CREATE INDEX IF NOT EXISTS hotword_finals_day ON hotword_finals(day)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS hotword_dictionaries "
                "(owner TEXT,id TEXT,title TEXT,format TEXT,enabled INTEGER,created_at REAL,"
                "source TEXT,report TEXT,PRIMARY KEY(owner,id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS hotword_dictionary_words "
                "(owner TEXT,dictionary_id TEXT,identity TEXT,text TEXT,weight INTEGER,"
                "frequency REAL,position INTEGER,PRIMARY KEY(owner,dictionary_id,identity))"
            )

    def settings(self, owner, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.settings(owner, connection)
        row = db.execute("SELECT * FROM hotword_settings WHERE owner=?", (owner,)).fetchone()
        return (json.loads(row["settings"]), row["revision"]) if row else (dict(DEFAULTS), 0)

    def update(self, owner, patch, revision):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, current = self.settings(owner, db)
            if type(revision) is not int or revision != current:
                raise HotwordConflict("热词设置已更新，请刷新后重试")
            settings = validate_settings(patch, previous)
            db.execute(
                "INSERT OR REPLACE INTO hotword_settings VALUES (?,?,?)",
                (owner, current + 1, json.dumps(settings, ensure_ascii=False)),
            )

    def advance_revision(self, db, owner, revision):
        settings, current = self.settings(owner, db)
        if type(revision) is not int or revision != current:
            raise HotwordConflict("热词设置或词库已更新，请刷新后重试")
        db.execute(
            "INSERT OR REPLACE INTO hotword_settings VALUES (?,?,?)",
            (owner, current + 1, json.dumps(settings, ensure_ascii=False)),
        )

    def dictionaries(self, owner, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.dictionaries(owner, connection)
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "format": row["format"],
                "enabled": bool(row["enabled"]),
                "createdAt": row["created_at"],
                "source": json.loads(row["source"]),
                "report": json.loads(row["report"]),
            }
            for row in db.execute(
                "SELECT * FROM hotword_dictionaries WHERE owner=? ORDER BY created_at,id", (owner,)
            )
        ]

    def import_dictionary(self, owner, title, parsed, source, revision):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise ValueError("词库名称须为 1–100 字符")
        identity = secrets.token_hex(12)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if len(self.dictionaries(owner, db)) >= MAX_DICTIONARIES:
                raise ValueError("每个 Key 最多 8 个词库，请先删除不需要的词库")
            self.advance_revision(db, owner, revision)
            db.execute(
                "INSERT INTO hotword_dictionaries VALUES (?,?,?,?,?,?,?,?)",
                (
                    owner,
                    identity,
                    title.strip(),
                    parsed["format"],
                    0,
                    time.time(),
                    json.dumps(source, ensure_ascii=False),
                    json.dumps(parsed["report"], ensure_ascii=False),
                ),
            )
            db.executemany(
                "INSERT INTO hotword_dictionary_words VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        owner,
                        identity,
                        word["text"].casefold(),
                        word["text"],
                        word["weight"],
                        word["frequency"],
                        word["position"],
                    )
                    for word in parsed["words"]
                ],
            )
        return identity

    def dictionary_words(self, owner, identity):
        with self.store.connection() as db:
            dictionary = next(
                (row for row in self.dictionaries(owner, db) if row["id"] == identity), None
            )
            if dictionary is None:
                return None
            words = [
                {"text": row["text"], "weight": row["weight"], "frequency": row["frequency"]}
                for row in db.execute(
                    "SELECT * FROM hotword_dictionary_words WHERE owner=? AND dictionary_id=? "
                    "ORDER BY frequency DESC,position,identity",
                    (owner, identity),
                )
            ]
            return {**dictionary, "words": words}

    def change_dictionary(self, owner, identity, patch, revision, *, delete=False):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM hotword_dictionaries WHERE owner=? AND id=?", (owner, identity)
            ).fetchone():
                return False
            self.advance_revision(db, owner, revision)
            if delete:
                db.execute(
                    "DELETE FROM hotword_dictionary_words WHERE owner=? AND dictionary_id=?",
                    (owner, identity),
                )
                db.execute(
                    "DELETE FROM hotword_dictionaries WHERE owner=? AND id=?", (owner, identity)
                )
            else:
                if not isinstance(patch, dict) or not patch or patch.keys() - {"title", "enabled"}:
                    raise ValueError("词库更新仅接受 title / enabled")
                if "enabled" in patch:
                    if type(patch["enabled"]) is not bool:
                        raise ValueError("enabled 必须为布尔值")
                    db.execute(
                        "UPDATE hotword_dictionaries SET enabled=? WHERE owner=? AND id=?",
                        (int(patch["enabled"]), owner, identity),
                    )
                if "title" in patch:
                    title = patch["title"]
                    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
                        raise ValueError("词库名称须为 1–100 字符")
                    db.execute(
                        "UPDATE hotword_dictionaries SET title=? WHERE owner=? AND id=?",
                        (title.strip(), owner, identity),
                    )
        return True

    @staticmethod
    def prune(db):
        cutoff = int(time.time() // 86400) - 89
        db.execute("DELETE FROM hotword_counts WHERE day < ?", (cutoff,))
        db.execute("DELETE FROM hotword_finals WHERE day < ?", (cutoff,))

    def observe(self, owner, event):
        if event.get("type") != "transcript.final" or not event.get("text", "").strip():
            return
        settings, _ = self.settings(owner)
        if not settings["autoLearn"]:
            return
        counts = Counter(extract_terms(event["text"], self.tokenizer))
        now = time.time()
        day = int(now // 86400)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck after extraction: disabling learning takes effect immediately.
            if not self.settings(owner, db)[0]["autoLearn"]:
                return
            inserted = db.execute(
                "INSERT OR IGNORE INTO hotword_finals VALUES (?,?,?)",
                (owner, event["utteranceId"], day),
            )
            if not inserted.rowcount:
                return
            self.prune(db)
            for text, count in counts.items():
                db.execute(
                    "INSERT INTO hotword_counts VALUES (?,?,?,?,?) "
                    "ON CONFLICT(owner,day,text) DO UPDATE SET "
                    "frequency=frequency+excluded.frequency,last_seen=excluded.last_seen",
                    (owner, day, text, count, now),
                )
            # Bound vocabulary growth, even for long-running shared servers.
            db.execute(
                "DELETE FROM hotword_counts WHERE owner=? AND day=? AND text IN "
                "(SELECT text FROM hotword_counts WHERE owner=? AND day=? "
                "ORDER BY frequency DESC,last_seen DESC,text LIMIT -1 OFFSET 5000)",
                (owner, day, owner, day),
            )

    def clear_statistics(self, owner):
        with self.store.connection() as db:
            db.execute("DELETE FROM hotword_counts WHERE owner=?", (owner,))
            # Keep final IDs to prevent replaying old results after clearing.

    def listing(self, owner, provider=None):
        with self.store.connection() as db:
            self.prune(db)
            settings, revision = self.settings(owner, db)
            cutoff = int(time.time() // 86400) - settings["windowDays"] + 1
            rows = db.execute(
                "SELECT text,SUM(frequency) AS frequency,MAX(last_seen) AS last_seen "
                "FROM hotword_counts WHERE owner=? AND day>=? GROUP BY text "
                "ORDER BY frequency DESC,last_seen DESC,text LIMIT 2000",
                (owner, cutoff),
            ).fetchall()
            dictionaries = self.dictionaries(owner, db)
        excluded = set(settings["excludedTerms"])
        learned = [
            {
                "text": row["text"],
                "frequency": row["frequency"],
                "lastSeen": row["last_seen"],
                "excluded": row["text"].casefold() in excluded,
            }
            for row in rows
        ]
        frequencies = {term["text"].casefold(): term["frequency"] for term in learned}
        terms = [
            {**term, "source": "manual", "frequency": frequencies.get(term["text"].casefold(), 0)}
            for term in settings["manualTerms"]
            if term["text"].casefold() not in excluded
        ]
        # Recommendations and observed words never enter recognition implicitly.
        # Only the explicit, saved personal table above is sent upstream.
        result = {
            "version": 1,
            "revision": revision,
            "settings": settings,
            "learnedTerms": learned,
            "terms": terms,
            "dictionaries": dictionaries,
            "dictionaryCandidateLimit": 0,  # Kept for v1; recommendations are not candidates.
            "personalTableOnly": True,
        }
        if provider is not None:
            result["selection"] = select_terms(provider, terms, settings)
        return result
