"""Portable authoring contracts for MSI optional service and UAC deployment."""

import base64
import importlib.util
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from openasrportal.entrypoints.service import initialize_foreground, load_config

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "portal_windows_build", ROOT / "scripts/build_windows.py"
)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
NS = {"w": "http://schemas.microsoft.com/wix/2006/wi"}


class WindowsMSITests(unittest.TestCase):
    def setUp(self):
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="msi-authoring-", dir=results)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.payload = self.directory / "payload"
        for name in (
            "OpenASRPortal.exe",
            "OpenASRPortal.xml",
            "PortalForeground.cmd",
            "PortalAdmin.url",
            "prepare_msi.ps1",
            "verify_msi.ps1",
            "remove_data.ps1",
            "Uninstall.exe",
            "python/python.exe",
        ):
            file = self.payload / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()
        output = self.directory / "portal.wxs"
        BUILD.wix(self.payload, output)
        self.root = ET.parse(output).getroot()

    def test_machine_installation_requests_uac_and_supports_optional_service(self):
        package = self.root.find(".//w:Package", NS)
        self.assertEqual(package.get("InstallScope"), "perMachine")
        self.assertEqual(package.get("InstallPrivileges"), "elevated")
        core = self.root.find(".//w:Feature[@Id='PortalCore']", NS)
        optional = self.root.find(".//w:Feature[@Id='PortalService']", NS)
        self.assertEqual(core.get("Absent"), "disallow")
        self.assertEqual(optional.get("Level"), "1")
        self.assertEqual(optional.get("Absent"), "disallow")
        self.assertEqual(self.root.find(".//w:UIRef", NS).get("Id"), "WixUI_InstallDir")
        optional_components = {entry.get("Id") for entry in optional.findall("w:ComponentRef", NS)}
        for component in self.root.findall(".//w:Component", NS):
            file = component.find("w:File", NS)
            if file is not None:
                self.assertEqual(
                    component.get("Id") in optional_components,
                    file.get("Name") in ("OpenASRPortal.exe", "OpenASRPortal.xml"),
                )

    def test_windows_installer_owns_service_and_prepares_state_as_system(self):
        service = self.root.find(".//w:ServiceInstall", NS)
        self.assertEqual(service.get("Account"), "NT AUTHORITY\\LocalService")
        control = self.root.find(".//w:ServiceControl", NS)
        self.assertEqual(control.get("Start"), "install")
        self.assertEqual(control.get("Stop"), "both")
        self.assertEqual(control.get("Remove"), "uninstall")
        event_values = self.root.findall(".//w:RegistryValue[@Name='EventMessageFile']", NS)
        self.assertEqual(len(event_values), 1)
        self.assertIn("EventLog\\Application\\OpenASRPortal", event_values[0].get("Key"))
        action = self.root.find(".//w:CustomAction[@Id='PreparePortalState']", NS)
        self.assertEqual(action.get("Execute"), "deferred")
        self.assertEqual(action.get("Impersonate"), "no")
        condition = self.root.find(".//w:Custom[@Action='PreparePortalState']", NS).text
        self.assertIn("&PortalService=3", condition)
        self.assertIn("NOT REMOVE", condition)
        commands = " ".join(
            action.get("Value", "") for action in self.root.findall(".//w:CustomAction", NS)
        )
        self.assertNotIn("apiKey", commands)
        self.assertNotIn(" install", commands)
        self.assertIn("-ExecutionPolicy Bypass", commands)

    def test_foreground_has_private_credentials_without_machine_state(self):
        config = self.directory / "user-only/nested/service.json"
        initialize_foreground(config)
        before = config.read_bytes()
        initialize_foreground(config)
        self.assertEqual(before, config.read_bytes())
        self.assertEqual(Path(load_config(config)["dataDir"]), config.parent / "data")

    def test_replacement_requires_consent_before_transaction_and_native_guard(self):
        confirm = self.root.find(
            ".//w:InstallUISequence/w:Custom[@Action='ConfirmReplacement']", NS
        )
        self.assertEqual(confirm.get("Before"), "ExecuteAction")
        guard = self.root.find(".//w:CustomAction[@Id='GuardReplacement']", NS)
        self.assertIsNotNone(guard.get("Error"))
        self.assertIsNone(guard.get("DllEntry"))
        execute = self.root.find(
            ".//w:InstallExecuteSequence/w:Custom[@Action='GuardReplacement']", NS
        )
        self.assertEqual(execute.get("Before"), "InstallInitialize")
        self.assertIn("REPLACE_PORTAL_PRODUCT", execute.text)
        self.assertIn("REPLACE_BUNDLE_PRODUCT", execute.text)
        self.assertIn("NOT REMOVE", execute.text)

    def test_installer_uses_neutral_reserved_artwork(self):
        image = self.directory / "banner.bmp"
        BUILD.installer_bitmap(image, 493, 58, banner=True)
        data = image.read_bytes()
        self.assertEqual(data[:2], b"BM")
        self.assertEqual(struct.unpack_from("<I", data, 2)[0], len(data))
        self.assertEqual(struct.unpack_from("<ii", data, 18), (493, 58))
        variables = {item.get("Id") for item in self.root.findall(".//w:WixVariable", NS)}
        self.assertIn("WixUIBannerBmp", variables)
        self.assertIn("WixUIDialogBmp", variables)

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("powershell"), "requires Windows PowerShell"
    )
    def test_xml_rewrite_works_in_windows_powershell(self):
        shutil.copy2(
            ROOT / "packaging/windows/OpenASRPortal.xml", self.directory / "OpenASRPortal.xml"
        )
        source = (ROOT / "packaging/windows/prepare_msi.ps1").read_text(encoding="utf-8")
        fragment = source[source.index("$xmlPath =") : source.index("$service = Get-Service")]
        script = (
            "$ErrorActionPreference='Stop'\n"
            "$ProgressPreference='SilentlyContinue'\n"
            "$InstallDir=$env:PORTAL_TEST_INSTALL\n"
            "$DataDir=Join-Path $InstallDir 'state data'\n"
            "$config=Join-Path $DataDir 'service.json'\n" + fragment
        )
        subprocess.run(
            [
                shutil.which("powershell"),
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ],
            env={**os.environ, "PORTAL_TEST_INSTALL": str(self.directory)},
            check=True,
            timeout=15,
        )
        xml = ET.parse(self.directory / "OpenASRPortal.xml").getroot()
        self.assertEqual(xml.findtext("logpath"), str(self.directory / "state data/logs"))
        self.assertIn(
            str(self.directory / "state data/service.json"), xml.findtext("startarguments")
        )


if __name__ == "__main__":
    unittest.main()
