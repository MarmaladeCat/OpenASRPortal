"""Inspect Portal ZIP; --live tests its private Python without installing a service."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    package = args.package.resolve()
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    assert package.with_suffix(".zip.sha256").read_text().split()[0] == digest
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bundle-check-", dir=results) as temporary:
        directory = Path(temporary)
        with zipfile.ZipFile(package) as archive:
            for name in archive.namelist():
                parts = Path(name).parts
                assert not Path(name).is_absolute() and ".." not in parts
                assert name.startswith("OpenASRPortal/")
                assert not name.endswith((".db", ".pyc", ".env"))
                assert "service.json" not in parts
            archive.extractall(directory)
        root = directory / "OpenASRPortal"
        metadata = json.loads((root / "build.json").read_text(encoding="utf-8"))
        assert (
            hashlib.sha256((root / "OpenASRPortal.exe").read_bytes()).hexdigest()
            == metadata["winswSha256"]
        )
        for name in (
            "service.ps1",
            "OpenASRPortal.xml",
            "WinSW-LICENSE.txt",
            "LICENSE",
            "python/python.exe",
            "app/openasrportal/presentation/web/index.html",
            "docs/user-guide.md",
            "docs/images/windows-admin.png",
            "docs/images/linux-admin.png",
            "tests/functional/manifest.json",
            "packaging/deployment/README.md",
            "packaging/deployment/compose.https.yaml",
            "scripts/create_tls_certificate.py",
        ):
            assert (root / name).is_file(), name
        assert (root / "python/python.exe").read_bytes()[:2] == b"MZ"
        assert (root / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
        if args.live:
            if os.name != "nt":
                raise RuntimeError("--live requires actual Windows")
            # Wrapper version parses the real XML/logging configuration, but does
            # not request UAC, register a service, or launch a recognition process.
            program_data = directory / "programdata"
            (program_data / "OpenASRPortal/logs").mkdir(parents=True)
            env = {**os.environ, "ProgramData": str(program_data), "PYTHONDONTWRITEBYTECODE": "1"}
            output = subprocess.check_output(
                [str(root / "OpenASRPortal.exe"), "version"], env=env, text=True, timeout=15
            )
            assert metadata["winsw"] in output, output
            python = root / "python/python.exe"
            subprocess.run(
                [str(python), "-B", str(ROOT / "tests/test_service.py"), "-v"],
                env=env,
                check=True,
                timeout=90,
            )
            assert not list(root.rglob("__pycache__"))
    print(
        "PASS Portal Windows bundle"
        + (": private runtime and graceful lifecycle" if args.live else "")
    )


if __name__ == "__main__":
    main()
