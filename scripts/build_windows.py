"""Build Portal's self-contained MSI with an optional Windows system service."""

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
windows_replacement = runpy.run_path(str(ROOT / "scripts/windows_replacement.py"))
CACHE = ROOT / ".cache/windows"
BUILD = ROOT / ".cache/build/windows"
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)[1]
PYTHON_VERSION = "3.13.16"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
WINSW_VERSION = "2.12.0"
WINSW_SHA256 = "b5066b7bbdfba1293e5d15cda3caaea88fbeab35bd5b38c41c913d492aadfc4f"
UPGRADE = uuid.UUID("64e55bb5-b8eb-40fa-bc40-089420d7c0a0")


def wix(payload, filename):
    namespace = "http://schemas.microsoft.com/wix/2006/wi"
    ET.register_namespace("", namespace)

    def element(parent, tag, **attributes):
        return ET.SubElement(parent, "{" + namespace + "}" + tag, attributes)

    document = ET.Element("{" + namespace + "}Wix")
    product = element(
        document,
        "Product",
        Id=str(uuid.uuid4()),
        Name="OpenASRPortal",
        Language="2052",
        Codepage="936",
        Version=VERSION,
        Manufacturer="OpenASRPortal",
        UpgradeCode=str(UPGRADE),
    )
    (payload / "uninstall.ini").write_text(
        "OpenASRPortal\n{" + product.attrib["Id"] + "}\n", encoding="utf-8"
    )
    element(
        product,
        "Package",
        InstallerVersion="500",
        Compressed="yes",
        InstallScope="perMachine",
        InstallPrivileges="elevated",
        Platform="x64",
    )
    element(product, "MediaTemplate", EmbedCab="yes")
    element(
        product,
        "MajorUpgrade",
        AllowSameVersionUpgrades="yes",
        Schedule="afterInstallInitialize",
        DowngradeErrorMessage="已安装更新版本的 OpenASRPortal。",
    )
    element(product, "Property", Id="ARPNOREPAIR", Value="1")
    element(product, "Property", Id="ARPSYSTEMCOMPONENT", Value="1")
    element(product, "Property", Id="REMOVEUSERDATA", Value="0", Secure="yes")
    for property_id, value_name in (("PORTALDATADIR", "StateDir"), ("INSTALLDIR", "InstallDir")):
        stored = element(product, "Property", Id=property_id, Secure="yes")
        element(
            stored,
            "RegistrySearch",
            Id="Previous" + property_id,
            Root="HKLM",
            Key="Software\\OpenASRPortal",
            Name=value_name,
            Type="raw",
            Win64="yes",
        )
    existing = element(product, "Property", Id="PORTAL_EXISTING_SERVICE")
    element(
        existing,
        "RegistrySearch",
        Id="ExistingService",
        Root="HKLM",
        Key="SYSTEM\\CurrentControlSet\\Services\\OpenASRPortal",
        Name="ImagePath",
        Type="raw",
        Win64="yes",
    )
    element(
        product, "Condition", Message="需要 Windows 10/11 或 Windows Server 的 x64 系统。"
    ).text = "Installed OR VersionNT64 >= 603"
    target = element(product, "Directory", Id="TARGETDIR", Name="SourceDir")
    program_files = element(target, "Directory", Id="ProgramFiles64Folder")
    install = element(program_files, "Directory", Id="INSTALLDIR", Name="OpenASRPortal")
    data = element(target, "Directory", Id="CommonAppDataFolder")
    element(data, "Directory", Id="PORTALDATADIR", Name="OpenASRPortal")
    menu = element(
        element(target, "Directory", Id="ProgramMenuFolder"),
        "Directory",
        Id="PortalMenu",
        Name="OpenASRPortal",
    )
    core = element(
        product,
        "Feature",
        Id="PortalCore",
        Title="Portal 程序（必选）",
        Description="独立运行时、管理网页和手动前台启动入口。",
        Level="1",
        Absent="disallow",
        ConfigurableDirectory="INSTALLDIR",
        Display="expand",
    )
    service = element(
        core,
        "Feature",
        Id="PortalService",
        Title="Portal 系统服务",
        Description="开机自动运行，不依赖用户登录。",
        Level="1",
        AllowAdvertise="no",
        InstallDefault="local",
        Absent="disallow",
    )
    directories = {Path("."): install}
    ids = {}
    for source in sorted(payload.rglob("*")):
        relative = source.relative_to(payload)
        identity = hashlib.sha1(relative.as_posix().encode()).hexdigest()[:24]
        if source.is_dir():
            directories[relative] = element(
                directories[relative.parent], "Directory", Id="D" + identity, Name=source.name
            )
            continue
        component_id, file_id = "C" + identity, "F" + identity
        ids[relative.as_posix()] = file_id
        component = element(
            directories[relative.parent],
            "Component",
            Id=component_id,
            Guid=str(uuid.uuid5(UPGRADE, relative.as_posix())),
            Win64="yes",
        )
        file_node = element(
            component,
            "File",
            Id=file_id,
            Name=source.name,
            Source="payload/" + relative.as_posix(),
            KeyPath="yes",
        )
        shortcut_titles = {
            "PortalForeground.cmd": "Portal 手动前台运行",
            "PortalAdmin.url": "Portal 管理网页",
            "Uninstall.exe": "Uninstall OpenASRPortal",
        }
        if relative.as_posix() in shortcut_titles:
            element(
                file_node,
                "Shortcut",
                Id="Shortcut" + identity,
                Name=shortcut_titles[relative.as_posix()],
                Directory=menu.attrib["Id"],
                Advertise="yes",
                WorkingDirectory="INSTALLDIR",
            )
        optional = relative.as_posix() in ("OpenASRPortal.exe", "OpenASRPortal.xml")
        element(service if optional else core, "ComponentRef", Id=component_id)
        if relative.as_posix() == "OpenASRPortal.exe":
            # WinSW's own install command normally creates this source. Native
            # MSI registration must do so too: LocalService cannot register an
            # event source when reporting a crash or shutdown failure.
            event_key = "SYSTEM\\CurrentControlSet\\Services\\EventLog\\Application\\OpenASRPortal"
            element(
                component,
                "RegistryValue",
                Root="HKLM",
                Key=event_key,
                Name="EventMessageFile",
                Type="expandable",
                Value="[WindowsFolder]Microsoft.NET\\Framework\\v4.0.30319\\EventLogMessages.dll",
            )
            element(
                component,
                "RegistryValue",
                Root="HKLM",
                Key=event_key,
                Name="TypesSupported",
                Type="integer",
                Value="7",
            )
            element(
                component,
                "ServiceInstall",
                Id="PortalServiceInstall",
                Name="OpenASRPortal",
                DisplayName="OpenASRPortal",
                Description="HTTP/WebSocket v1 语音门户",
                Type="ownProcess",
                Start="auto",
                ErrorControl="normal",
                Account="NT AUTHORITY\\LocalService",
                Vital="yes",
            )
            element(
                component,
                "ServiceControl",
                Id="PortalServiceControl",
                Name="OpenASRPortal",
                Start="install",
                Stop="both",
                Remove="uninstall",
                Wait="yes",
            )
            util = "http://schemas.microsoft.com/wix/UtilExtension"
            ET.SubElement(
                component,
                "{" + util + "}ServiceConfig",
                {
                    "ServiceName": "OpenASRPortal",
                    "FirstFailureActionType": "restart",
                    "SecondFailureActionType": "restart",
                    "ThirdFailureActionType": "restart",
                    "RestartServiceDelayInSeconds": "10",
                    "ResetPeriodInDays": "1",
                },
            )
    shortcuts = element(
        install,
        "Component",
        Id="PortalShortcuts",
        Guid=str(uuid.uuid5(UPGRADE, "shortcuts")),
        Win64="yes",
    )
    element(
        shortcuts,
        "RegistryValue",
        Root="HKLM",
        Key="Software\\OpenASRPortal",
        Name="InstallDir",
        Type="string",
        Value="[INSTALLDIR]",
        KeyPath="yes",
    )
    element(
        shortcuts,
        "RegistryValue",
        Root="HKLM",
        Key="Software\\OpenASRPortal",
        Name="StateDir",
        Type="string",
        Value="[PORTALDATADIR]",
    )
    element(
        shortcuts, "RemoveFolder", Id="RemovePortalMenu", Directory="PortalMenu", On="uninstall"
    )
    for directory in directories.values():
        element(
            shortcuts,
            "RemoveFolder",
            Id="Remove" + directory.attrib["Id"],
            Directory=directory.attrib["Id"],
            On="uninstall",
        )
    element(core, "ComponentRef", Id="PortalShortcuts")
    for name, value, kind in (
        ("DisplayName", "OpenASRPortal", "string"),
        ("DisplayVersion", VERSION, "string"),
        ("Publisher", "OpenASRPortal", "string"),
        ("InstallLocation", "[INSTALLDIR]", "string"),
        ("DisplayIcon", "[INSTALLDIR]Uninstall.exe", "string"),
        ("UninstallString", '"[INSTALLDIR]Uninstall.exe"', "string"),
        ("QuietUninstallString", '"[INSTALLDIR]Uninstall.exe" --quiet', "string"),
        ("NoModify", "1", "integer"),
        ("NoRepair", "1", "integer"),
    ):
        element(
            shortcuts,
            "RegistryValue",
            Root="HKLM",
            Key="Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\OpenASRPortal",
            Name=name,
            Type=kind,
            Value=value,
        )
    sequence = element(product, "InstallExecuteSequence")
    element(
        product,
        "CustomAction",
        Id="SetInstallLocation",
        Property="ARPINSTALLLOCATION",
        Value="[INSTALLDIR]",
    )
    element(
        sequence, "Custom", Action="SetInstallLocation", After="CostFinalize"
    ).text = "NOT REMOVE"
    windows_replacement["author"](
        element, product, sequence, "portal", "payload/Replacement.CA.dll"
    )
    element(
        product,
        "CustomAction",
        Id="RefuseForeignService",
        Error="检测到非 MSI 管理的同名服务。请先停止并取消旧服务注册；数据不会被删除。",
    )
    element(
        sequence, "Custom", Action="RefuseForeignService", Before="InstallInitialize"
    ).text = "&PortalService=3 AND NOT (!PortalService=3) AND NOT WIX_UPGRADE_DETECTED AND PORTAL_EXISTING_SERVICE"
    command = (
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile '
        '-NonInteractive -ExecutionPolicy Bypass -File "[#' + ids["prepare_msi.ps1"] + ']" '
        '-Python "[#' + ids["python/python.exe"] + ']" '
        '-DataDir "[PORTALDATADIR]." -InstallDir "[INSTALLDIR]."'
    )
    element(
        product,
        "CustomAction",
        Id="SetPreparePortalState",
        Property="PreparePortalState",
        Value=command,
    )
    element(
        product,
        "CustomAction",
        Id="PreparePortalState",
        BinaryKey="WixCA",
        DllEntry="WixQuietExec",
        Execute="deferred",
        Return="check",
        Impersonate="no",
    )
    condition = '&PortalService=3 AND NOT REMOVE~="ALL"'
    element(
        sequence, "Custom", Action="SetPreparePortalState", After="InstallFiles"
    ).text = condition
    element(
        sequence, "Custom", Action="PreparePortalState", After="SetPreparePortalState"
    ).text = condition
    verify_command = (
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile '
        '-NonInteractive -ExecutionPolicy Bypass -File "[#' + ids["verify_msi.ps1"] + ']" '
        '-DataDir "[PORTALDATADIR]."'
    )
    element(
        product,
        "CustomAction",
        Id="SetVerifyPortalService",
        Property="VerifyPortalService",
        Value=verify_command,
    )
    element(
        product,
        "CustomAction",
        Id="VerifyPortalService",
        BinaryKey="WixCA",
        DllEntry="WixQuietExec",
        Execute="deferred",
        Return="check",
        Impersonate="no",
    )
    element(
        sequence, "Custom", Action="SetVerifyPortalService", After="StartServices"
    ).text = condition
    element(
        sequence, "Custom", Action="VerifyPortalService", After="SetVerifyPortalService"
    ).text = condition
    cleanup = (
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive '
        '-ExecutionPolicy Bypass -File "[#' + ids["remove_data.ps1"] + ']" '
        '-DataDir "[PORTALDATADIR]." -UserDataDir "[LocalAppDataFolder]OpenASRPortal" -AllUsers'
    )
    element(
        product,
        "CustomAction",
        Id="SetRemovePortalData",
        Property="RemovePortalData",
        Value=cleanup,
    )
    element(
        product,
        "CustomAction",
        Id="RemovePortalData",
        BinaryKey="WixCA",
        DllEntry="WixQuietExec",
        Execute="deferred",
        Return="check",
        Impersonate="no",
    )
    wipe = 'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE AND REMOVEUSERDATA="1"'
    element(sequence, "Custom", Action="SetRemovePortalData", After="StopServices").text = wipe
    element(sequence, "Custom", Action="RemovePortalData", After="SetRemovePortalData").text = wipe
    element(product, "UIRef", Id="WixUI_InstallDir")
    element(product, "Property", Id="WIXUI_INSTALLDIR", Value="INSTALLDIR")
    element(product, "WixVariable", Id="WixUIBannerBmp", Value="installer-banner.bmp")
    element(product, "WixVariable", Id="WixUIDialogBmp", Value="installer-dialog.bmp")
    ui = element(product, "UI")
    # No product license has been supplied: don't display WiX's placeholder EULA.
    element(
        ui,
        "Publish",
        Dialog="WelcomeDlg",
        Control="Next",
        Event="NewDialog",
        Value="InstallDirDlg",
        Order="2",
    ).text = "NOT Installed"
    element(
        ui,
        "Publish",
        Dialog="InstallDirDlg",
        Control="Back",
        Event="NewDialog",
        Value="WelcomeDlg",
        Order="2",
    ).text = "NOT Installed"
    ET.ElementTree(document).write(filename, encoding="utf-8", xml_declaration=True)


def installer_bitmap(path, width, height, banner=False):
    """Neutral reserved artwork instead of WiX's unrelated default red logo."""
    rows = []
    for y in range(height - 1, -1, -1):
        row = bytearray()
        for x in range(width):
            color = (255, 255, 255) if banner or x >= 164 else (241, 245, 249)
            left, top, size = (width - 49, 12, 32) if banner else (56, 48, 52)
            if left <= x < left + size and top <= y < top + size:
                color = (100, 116, 139)
                inset = size // 3
                if (
                    left + inset <= x < left + size - inset
                    and top + inset <= y < top + size - inset
                ):
                    edge = min(
                        x - left - inset,
                        left + size - inset - x - 1,
                        y - top - inset,
                        top + size - inset - y - 1,
                    )
                    if edge < 2:
                        color = (255, 255, 255)
            row.extend(reversed(color))
        row.extend(b"\0" * ((-len(row)) % 4))
        rows.append(row)
    pixels = b"".join(rows)
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    path.write_bytes(header + dib + pixels)


def build_msi(payload, stage, destination, wix_bin):
    if os.name != "nt":
        raise RuntimeError(
            "MSI build requires Windows/WiX 3.14; use --format zip for a portable build"
        )
    if wix_bin is None:
        configured = os.environ.get("OPENASRPORTAL_WIX_BIN") or os.environ.get("WIX")
        if configured:
            wix_bin = Path(configured)
            if not (wix_bin / "candle.exe").is_file():
                wix_bin = wix_bin / "bin"
    candle = str(wix_bin / "candle.exe") if wix_bin else shutil.which("candle")
    light = str(wix_bin / "light.exe") if wix_bin else shutil.which("light")
    if not all(path and Path(path).is_file() for path in (candle, light)):
        raise RuntimeError("WiX 3.14 is required; pass --wix-bin (no .NET SDK or C++ tools needed)")
    windows_replacement["build"](ROOT, payload, Path(candle).parent)
    source = stage / "portal.wxs"
    installer_bitmap(stage / "installer-banner.bmp", 493, 58, banner=True)
    installer_bitmap(stage / "installer-dialog.bmp", 493, 312)
    wix(payload, source)
    extensions = [
        "-ext",
        str(Path(candle).parent / "WixUIExtension.dll"),
        "-ext",
        str(Path(candle).parent / "WixUtilExtension.dll"),
    ]
    subprocess.run(
        [
            candle,
            "-nologo",
            "-arch",
            "x64",
            *extensions,
            "-out",
            str(stage / "portal.wixobj"),
            str(source),
        ],
        cwd=stage,
        check=True,
    )
    subprocess.run(
        [
            light,
            "-nologo",
            "-sice:ICE61",
            "-cultures:zh-cn",
            *extensions,
            "-out",
            str(destination),
            str(stage / "portal.wixobj"),
        ],
        cwd=stage,
        check=True,
    )


def download(url, destination, digest):
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
        return
    temporary = destination.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise ValueError("Download SHA-256 mismatch: " + destination.name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_runtime(payload):
    archive = CACHE / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{archive.name}", archive, PYTHON_SHA256
    )
    with zipfile.ZipFile(archive) as source:
        source.extractall(payload / "python")
    (payload / "python/python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n../app\nimport site\n", encoding="utf-8"
    )
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    # jieba is pure Python but upstream publishes only an sdist. Build its universal
    # wheel locally; all native dependencies must have actual Windows cp313 wheels.
    pure = [requirement for requirement in requirements if requirement.startswith("jieba==")]
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(CACHE), *pure],
        check=True,
    )
    wheels = list(CACHE.glob("jieba-0.42.1-*-none-any.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected one universal jieba wheel")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(payload / "python/Lib/site-packages"),
            "--platform",
            "win_amd64",
            "--python-version",
            "3.13",
            "--only-binary=:all:",
            "--no-compile",
            "--ignore-installed",
            "--no-warn-conflicts",
            *[requirement for requirement in requirements if requirement not in pure],
            str(wheels[0]),
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/build/artifacts/windows/amd64/native"
    )
    parser.add_argument("--format", choices=("msi", "zip"), default="msi")
    parser.add_argument("--wix-bin", type=Path, help="WiX 3.14 binaries directory (MSI builds)")
    args = parser.parse_args()
    for directory in (CACHE, BUILD, args.output):
        directory.mkdir(parents=True, exist_ok=True)
    # Use the OS-serviced .NET Framework, not the wrapper's EOL .NET Core 3.1 bundle.
    winsw = CACHE / f"WinSW.NET461-{WINSW_VERSION}.exe"
    download(
        f"https://github.com/winsw/winsw/releases/download/v{WINSW_VERSION}/WinSW.NET461.exe",
        winsw,
        WINSW_SHA256,
    )
    with tempfile.TemporaryDirectory(prefix="bundle-", dir=BUILD) as temporary:
        stage = Path(temporary)
        payload = stage / "payload"
        shutil.copytree(
            ROOT / "packaging/windows",
            payload,
            ignore=shutil.ignore_patterns("service.ps1") if args.format == "msi" else None,
        )
        shutil.copy2(winsw, payload / "OpenASRPortal.exe")
        shutil.copytree(
            ROOT / "src/openasrportal",
            payload / "app/openasrportal",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(ROOT / "docs", payload / "docs")
        shutil.copy2(ROOT / "README.md", payload / "README.md")
        shutil.copy2(ROOT / "README.zh-CN.md", payload / "README.zh-CN.md")
        shutil.copy2(ROOT / "LICENSE", payload / "LICENSE")
        for name in (
            "tests/functional/manifest.json",
            "packaging/deployment/README.md",
            "packaging/deployment/README.zh-CN.md",
            "packaging/deployment/compose.yaml",
            "packaging/deployment/compose.https.yaml",
            "packaging/deployment/.env.example",
            "packaging/nginx/portal.conf",
            "scripts/create_tls_certificate.py",
        ):
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        prepare_runtime(payload)
        if args.format == "msi":
            csc = (
                Path(os.environ.get("WINDIR", r"C:\Windows"))
                / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
            )
            subprocess.run(
                [
                    str(csc),
                    "/nologo",
                    "/target:winexe",
                    "/codepage:65001",
                    "/reference:System.Windows.Forms.dll",
                    "/reference:System.Core.dll",
                    "/reference:System.ServiceProcess.dll",
                    "/out:" + str(payload / "Uninstall.exe"),
                    str(ROOT / "packaging/windows/Uninstall.cs"),
                ],
                check=True,
            )
        metadata = {
            "product": "OpenASRPortal",
            "version": VERSION,
            "platform": "windows",
            "architecture": "amd64",
            "python": PYTHON_VERSION,
            "pythonSha256": PYTHON_SHA256,
            "winsw": WINSW_VERSION,
            "winswSha256": WINSW_SHA256,
            "validation": "built-on-windows" if os.name == "nt" else "cross-built-unverified",
        }
        (payload / "build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        destination = args.output.resolve() / f"OpenASRPortal_{VERSION}_win-x64.{args.format}"
        if args.format == "msi":
            build_msi(payload, stage, destination, args.wix_bin)
        else:
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(payload.rglob("*")):
                    if file.is_file():
                        archive.write(file, Path("OpenASRPortal") / file.relative_to(payload))
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        symbols = destination.with_suffix(".wixpdb")
        if symbols.exists():
            symbols.replace(BUILD / symbols.name)
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            digest + "  " + destination.name + "\n"
        )
        print(destination)


if __name__ == "__main__":
    main()
