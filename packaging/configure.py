"""Install network/path configuration only; credentials are owned by Portal DB."""

import argparse
import json
import os
from pathlib import Path


def configure(root):
    directory = root / "etc/openasrportal"
    directory.mkdir(parents=True, exist_ok=True)
    environment = directory / "service.env"
    if not environment.exists():
        values = {
            "OPENASRPORTAL_HOST": "127.0.0.1",
            "OPENASRPORTAL_PORT": "10087",
            "OPENASRPORTAL_DATA": "/var/lib/openasrportal",
        }
        with os.fdopen(
            os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640), "w"
        ) as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    lines = environment.read_text(encoding="utf-8").splitlines()
    retained = [
        line
        for line in lines
        if line.partition("=")[0].strip()
        not in {"OPENASRPORTAL_API_KEY", "OPENASRPORTAL_ADMIN_KEY"}
    ]
    if retained != lines:
        temporary = environment.with_suffix(".tmp")
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640), "w", encoding="utf-8"
        ) as stream:
            stream.write("\n".join(retained) + "\n")
        temporary.replace(environment)
    # Retire only the known generated public credential handoff. Unknown files
    # are preserved but made private, never imported as authentication defaults.
    client = directory / "client.json"
    if client.is_file():
        try:
            value = json.loads(client.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            value = None
        if isinstance(value, dict) and set(value) == {"url", "apiKey", "profileId"}:
            client.unlink()
        else:
            client.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    configure(parser.parse_args().root)
