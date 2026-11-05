"""Inspect the real MSI and optionally run its extracted runtime (no host install)."""

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def table(package, name):
    installer = ctypes.WinDLL("msi", use_last_error=True)
    handle = ctypes.c_uint
    installer.MsiOpenDatabaseW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(handle),
    ]
    installer.MsiDatabaseOpenViewW.argtypes = [handle, ctypes.c_wchar_p, ctypes.POINTER(handle)]
    installer.MsiViewExecute.argtypes = [handle, handle]
    installer.MsiViewFetch.argtypes = [handle, ctypes.POINTER(handle)]
    installer.MsiRecordGetFieldCount.argtypes = [handle]
    installer.MsiRecordGetStringW.argtypes = [
        handle,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    installer.MsiCloseHandle.argtypes = [handle]
    database, view = handle(), handle()

    def check(result):
        if result:
            raise OSError(result, "Windows Installer query failed: " + name)

    try:
        check(installer.MsiOpenDatabaseW(str(package), None, ctypes.byref(database)))
        check(
            installer.MsiDatabaseOpenViewW(database, f"SELECT * FROM `{name}`", ctypes.byref(view))
        )
        check(installer.MsiViewExecute(view, 0))
        rows = []
        while True:
            record = handle()
            result = installer.MsiViewFetch(view, ctypes.byref(record))
            if result == 259:
                return rows
            check(result)
            try:
                row = []
                for column in range(1, installer.MsiRecordGetFieldCount(record) + 1):
                    length = ctypes.c_uint(65535)
                    text = ctypes.create_unicode_buffer(length.value + 1)
                    check(installer.MsiRecordGetStringW(record, column, text, ctypes.byref(length)))
                    row.append(text.value)
                rows.append(row)
            finally:
                installer.MsiCloseHandle(record)
    finally:
        if view.value:
            installer.MsiCloseHandle(view)
        if database.value:
            installer.MsiCloseHandle(database)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("MSI inspection requires Windows Installer")
    package = args.package.resolve()
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    assert package.with_suffix(".msi.sha256").read_text().split()[0] == digest
    properties = dict(table(package, "Property"))
    assert properties["ALLUSERS"] == "1"
    assert properties.get("ARPNOMODIFY") == "1"  # No optional standalone features.
    features = {row[0]: row for row in table(package, "Feature")}
    assert "PortalService" in features and "PortalCore" in features
    optional = features["PortalService"]
    assert optional[5] == "1"
    assert int(optional[7]) & 16  # Standalone service is now mandatory.
    service = table(package, "ServiceInstall")[0]
    assert service[1] == "OpenASRPortal" and service[8] == "NT AUTHORITY\\LocalService"
    assert len(table(package, "ServiceControl")) == 1
    actions = {row[0]: row for row in table(package, "CustomAction")}
    assert int(actions["PreparePortalState"][1]) & (1024 | 2048) == 3072
    dialogs = {row[0] for row in table(package, "Dialog")}
    assert "InstallDirDlg" in dialogs and "VerifyReadyDlg" in dialogs
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="msi-extract-", dir=results) as temporary:
        directory = Path(temporary)
        subprocess.run(
            [
                "msiexec.exe",
                "/a",
                str(package),
                "/qn",
                "TARGETDIR=" + str(directory),
                "/l*v",
                str(directory / "extract.log"),
            ],
            check=True,
            timeout=90,
        )
        wrapper = next(directory.rglob("OpenASRPortal.exe"))
        root = wrapper.parent
        metadata = json.loads((root / "build.json").read_text(encoding="utf-8"))
        assert hashlib.sha256(wrapper.read_bytes()).hexdigest() == metadata["winswSha256"]
        assert not list(root.rglob("service.json")) and not list(root.rglob("portal.db"))
        assert (root / "PortalForeground.cmd").is_file()
        if args.live:
            python = root / "python/python.exe"
            subprocess.run(
                [str(python), "-B", str(ROOT / "tests/test_service.py"), "-v"],
                check=True,
                timeout=90,
            )
        assert not list(root.rglob("__pycache__"))
    print("PASS Portal MSI: optional service, UAC, native lifecycle, extracted private runtime")


if __name__ == "__main__":
    main()
