"""显式导入旧业务 ASR 配置，源数据库只读且不删除任何记录。"""

import argparse
import json
import sqlite3
from pathlib import Path

from ..domain.config import REMOTE_MODELS
from ..storage.store import Store


def import_notes(database, directory):
    source = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = source.execute("SELECT name,value FROM settings WHERE name LIKE 'asr:%'").fetchall()
    finally:
        source.close()
    # 完整解析后才开始导入；不回显 Key。
    records = [(name.removeprefix("asr:"), json.loads(value)) for name, value in rows]
    store = Store(directory)
    imported = []
    for provider, configuration in records:
        if provider in REMOTE_MODELS and configuration.get("apiKey"):
            profile_id = "migrated-" + provider
            if store.get(profile_id):
                continue
            store.save(profile_id, "迁移配置 · " + provider, provider, configuration)
            imported.append(profile_id)
    return imported


def main():
    parser = argparse.ArgumentParser(description="Import old Notes ASR profiles explicitly")
    parser.add_argument("--notes-db", required=True)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    print("Imported profiles:", ", ".join(import_notes(args.notes_db, args.data_dir)))


if __name__ == "__main__":
    main()
