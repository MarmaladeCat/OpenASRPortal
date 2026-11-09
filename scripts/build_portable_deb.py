"""Build independent Portal debs on Ubuntu 22.04 with a private Python runtime."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("amd64", "arm64"), default="amd64")
    parser.add_argument("--build-network")
    parser.add_argument("--skip-image-build", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    image = "openasrportal-build:ubuntu22.04-" + args.arch
    if not args.skip_image_build:
        command = [
            "docker",
            "build",
            "--platform",
            "linux/" + args.arch,
            "-f",
            "packaging/docker/Dockerfile.portable",
            "-t",
            image,
        ]
        if args.build_network:
            command += ["--network", args.build_network]
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            command += ["--build-arg", name]
        subprocess.run([*command, "."], cwd=ROOT, check=True)
    work = ROOT / ".cache/build/portable" / args.arch
    output = args.output.resolve() if args.output else ROOT / ".cache/build/artifacts/linux" / args.arch / "service"
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    commands = [
        ["python", "/source/scripts/build_runtime.py"],
        [
            "python",
            "/source/scripts/build_deb.py",
            "--python",
            "python",
            "--runtime-dir",
            "/build/runtime/openasrportal-runtime",
            "--output",
            "/artifacts",
        ],
    ]
    code = "import subprocess; " + "; ".join(
        "subprocess.run(" + repr(command) + ", check=True)" for command in commands
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/" + args.arch,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-e",
            "OPENASRPORTAL_BUILD_DIR=/build",
            "-v",
            f"{ROOT}:/source:ro",
            "-v",
            f"{work}:/build",
            "-v",
            f"{output}:/artifacts",
            image,
            "python",
            "-c",
            code,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
