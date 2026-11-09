"""Freeze Portal's own Python and dependencies; no system Python ABI at installation."""

import os
import subprocess
import sys
from pathlib import Path

from runtime_cache import fingerprint, record, reusable
ROOT = Path(__file__).resolve().parents[1]


def main():
    build = Path(os.environ.get("OPENASRPORTAL_BUILD_DIR", ROOT / "build"))
    marker = build / "runtime-cache.json"
    output = build / "runtime/openasrportal-runtime"
    key = fingerprint(ROOT)
    if reusable(marker, key, output):
        print("Reusing verified frozen Portal runtime", flush=True)
        return
    marker.unlink(missing_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "openasrportal-runtime",
            "--distpath",
            str(build / "runtime"),
            "--workpath",
            str(build / "pyinstaller"),
            "--specpath",
            str(build / "pyinstaller"),
            "--paths",
            str(ROOT / "src"),
            "--paths",
            str(ROOT / "packaging"),
            "--add-data",
            str(ROOT / "src/openasrportal/presentation") + ":openasrportal/presentation",
            "--collect-all",
            "jieba",
            "--collect-data",
            "tzdata",
            str(ROOT / "packaging/runtime_entry.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    record(marker, key, output)


if __name__ == "__main__":
    main()
