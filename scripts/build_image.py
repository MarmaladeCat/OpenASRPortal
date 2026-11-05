"""Build and export the product's own Docker image with an offline deployment kit."""

import argparse
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from release import identity

ROOT = Path(__file__).resolve().parents[1]


def build(arch, network=None):
    name, version = identity()
    image = f"{name.lower()}:{version}-linux-{arch}"
    command = [
        "docker",
        "build",
        "--platform",
        "linux/" + arch,
        "-f",
        "packaging/docker/Dockerfile",
        "-t",
        image,
        "--label",
        "org.opencontainers.image.version=" + version,
    ]
    if network:
        command += ["--network", network]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        command += ["--build-arg", key]
    subprocess.run([*command, "."], cwd=ROOT, check=True)
    metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
    if metadata["Os"] != "linux" or metadata["Architecture"] != arch:
        raise RuntimeError("Docker image OS/architecture mismatch")
    output = ROOT / ".cache/build/artifacts/linux" / arch / "container"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache/build") as temporary:
        payload = Path(temporary) / name
        payload.mkdir()
        for filename in (
            "compose.yaml",
            ".env.example",
            "README.md",
            "README.zh-CN.md",
            "compose.https.yaml",
        ):
            shutil.copy2(ROOT / "packaging/deployment" / filename, payload)
        shutil.copy2(ROOT / "LICENSE", payload / "LICENSE")
        shutil.copytree(ROOT / "packaging/nginx", payload / "nginx")
        shutil.copy2(ROOT / "scripts/create_tls_certificate.py", payload)
        example = payload / ".env.example"
        example.write_text(example.read_text().replace("@IMAGE@", image))
        subprocess.run(
            ["docker", "image", "save", "-o", str(payload / "image.tar"), image], check=True
        )
        (payload / "image.json").write_text(
            json.dumps(
                {
                    "product": name,
                    "version": version,
                    "tag": image,
                    "id": metadata["Id"],
                    "platform": "linux/" + arch,
                },
                indent=2,
            )
            + "\n"
        )
        target = output / f"{name}_{version}_linux_{arch}_docker.tar.gz"
        with tarfile.open(target, "w:gz", compresslevel=1) as archive:
            archive.add(payload, arcname=name)
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--build-network")
    args = parser.parse_args()
    build(args.arch, args.build_network)
