"""Build an independent Portal system-service deb with private runtime dependencies.

Build on the target distribution/architecture. No pip/network access at install time.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(
    1
)


def build(output, python, runtime_dir=None):
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    minor = json.loads(
        subprocess.check_output(
            [python, "-c", "import json,sys; print(json.dumps(list(sys.version_info[:2])))"],
            text=True,
        )
    )
    if minor < [3, 10]:
        raise ValueError("Portal requires Python 3.10+")
    output.mkdir(parents=True, exist_ok=True)
    build_root = Path(os.environ.get("OPENASRPORTAL_BUILD_DIR", ROOT / "build"))
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deb-", dir=build_root) as directory:
        stage = Path(directory)
        app = stage / "usr/lib/openasrportal"
        shutil.copytree(
            ROOT / "src/openasrportal",
            app / "openasrportal",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if runtime_dir:
            shutil.copytree(runtime_dir, app / "runtime", symlinks=True)
        else:
            install_vendor(app, python)
        shutil.copy2(ROOT / "packaging/configure.py", app / "configure.py")
        documents = stage / "usr/share/doc/openasrportal"
        documents.mkdir(parents=True)
        shutil.copy2(ROOT / "LICENSE", documents / "copyright")
        binary = stage / "usr/bin/openasrportal"
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\n"
            'HERE=$(CDPATH= cd -- "$(dirname -- "$0")/../lib/openasrportal" && pwd)\n'
            + (
                'unset PYTHONPATH PYTHONHOME\nexec "$HERE/runtime/openasrportal-runtime" "$@"\n'
                if runtime_dir
                else 'export PYTHONPATH="$HERE:$HERE/vendor"\nexec /usr/bin/python3 -m openasrportal "$@"\n'
            )
        )
        binary.chmod(0o755)
        units = stage / "usr/lib/systemd/system"
        units.mkdir(parents=True)
        shutil.copy2(ROOT / "packaging/openasrportal.service", units)
        control = stage / "DEBIAN"
        control.mkdir()
        version = ".".join(map(str, minor))
        upper = f"{minor[0]}.{minor[1] + 1}"
        depends = (
            "libc6 (>= 2.35), libgcc-s1, libstdc++6 (>= 11), zlib1g, ca-certificates"
            if runtime_dir
            else f"python3 (>= {version}), python3 (<< {upper})"
        )
        (control / "control").write_text(
            f"Package: openasrportal\nVersion: {VERSION}\nArchitecture: {architecture}\n"
            "Maintainer: OpenASRPortal maintainers\nSection: net\nPriority: optional\n"
            f"Depends: {depends}, adduser, init-system-helpers\n"
            "Description: OpenASRPortal independent HTTP/WebSocket speech service\n"
        )
        for name in ("postinst", "prerm", "postrm"):
            shutil.copy2(ROOT / "packaging" / name, control / name)
            (control / name).chmod(0o755)
        if not runtime_dir:
            add_native_dependencies(stage, app, control)
        package = output / f"openasrportal_{VERSION}_{architecture}.deb"
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True
        )
    return package


def install_vendor(app, python):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--python",
            python,
            "install",
            "--only-binary=:all:",
            "--no-binary=jieba",
            "--no-compile",
            "--ignore-installed",
            "--no-warn-conflicts",
            "--target",
            str(app / "vendor"),
            "-r",
            str(ROOT / "requirements.txt"),
        ],
        check=True,
    )


def add_native_dependencies(stage, app, control):
    metadata = stage / "debian"
    metadata.mkdir()
    (metadata / "control").write_text(
        "Source: openasrportal\nSection: net\nPriority: optional\n"
        "Maintainer: OpenASRPortal maintainers\n\n"
        "Package: openasrportal\nArchitecture: any\nDescription: Speech service\n"
    )
    libraries = list((app / "vendor").rglob("*.so"))
    native = subprocess.check_output(
        ["dpkg-shlibdeps", "-O", *["-e" + str(file) for file in libraries]],
        cwd=stage,
        text=True,
    )
    native_depends = next(
        line.split("=", 1)[1] for line in native.splitlines() if line.startswith("shlibs:Depends=")
    )
    control_file = control / "control"
    control_file.write_text(
        control_file.read_text().replace(
            "adduser, init-system-helpers\n",
            f"adduser, init-system-helpers, {native_depends}\n",
        )
    )
    shutil.rmtree(metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".cache/build/artifacts/linux" / architecture / "service",
    )
    parser.add_argument("--python", default="/usr/bin/python3", help="target system interpreter")
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument(
        "--system-python", action="store_true", help="explicit distribution-specific ABI build"
    )
    args = parser.parse_args()
    if args.runtime_dir or args.system_python:
        print(build(args.output.resolve(), args.python, args.runtime_dir))
    else:
        command = [
            sys.executable,
            str(ROOT / "scripts/build_portable_deb.py"),
            "--arch",
            architecture,
            "--output",
            str(args.output.resolve()),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
