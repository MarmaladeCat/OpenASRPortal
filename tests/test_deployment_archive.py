"""The Docker kit must retain its authored deployment guide and runnable resources."""

import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        "portal_" + name, ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeploymentArchiveTests(unittest.TestCase):
    def test_current_templates_package_without_obsolete_documents(self):
        # Only Docker build/save are substituted; archive assembly uses the real script.
        with patch.dict(sys.modules, {"release": load_script("release")}):
            builder = load_script("build_image")
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="deployment-docs-", dir=results) as temporary:
            directory = Path(temporary)
            shutil.copy2(ROOT / "LICENSE", directory / "LICENSE")
            for name in ("packaging/deployment", "packaging/nginx"):
                shutil.copytree(ROOT / name, directory / name)
            (directory / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts/create_tls_certificate.py", directory / "scripts")

            def docker(command, **kwargs):
                if command[:3] == ["docker", "image", "save"]:
                    Path(command[4]).write_bytes(b"isolated image fixture")
                else:
                    self.assertEqual(command[:2], ["docker", "build"])

            metadata = {"Os": "linux", "Architecture": "amd64", "Id": "sha256:fixture"}
            with (
                patch.object(builder, "ROOT", directory),
                patch.object(builder.subprocess, "run", side_effect=docker),
                patch.object(
                    builder.subprocess, "check_output", return_value=json.dumps([metadata])
                ),
            ):
                builder.build("amd64")
            archive = next((directory / ".cache/build/artifacts").rglob("*.tar.gz"))
            with tarfile.open(archive) as package:
                for name in ("README.md", "README.zh-CN.md", "compose.yaml", "compose.https.yaml"):
                    self.assertEqual(
                        package.extractfile("OpenASRPortal/" + name).read(),
                        (ROOT / "packaging/deployment" / name).read_bytes(),
                    )
                for name, source in (
                    ("LICENSE", "LICENSE"),
                    ("nginx/portal.conf", "packaging/nginx/portal.conf"),
                    ("create_tls_certificate.py", "scripts/create_tls_certificate.py"),
                ):
                    self.assertEqual(
                        package.extractfile("OpenASRPortal/" + name).read(),
                        (ROOT / source).read_bytes(),
                    )
                self.assertNotIn("OpenASRPortal/HTTPS.md", package.getnames())
                self.assertNotIn(
                    b"@IMAGE@", package.extractfile("OpenASRPortal/.env.example").read()
                )
                self.assertEqual(
                    package.extractfile("OpenASRPortal/image.tar").read(), b"isolated image fixture"
                )


if __name__ == "__main__":
    unittest.main()
