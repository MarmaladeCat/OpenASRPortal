"""Install network/path configuration only; credentials are owned by Portal DB."""

import argparse
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path


def environment_values(text):
    """Read installer-owned systemd assignments, including quoted custom paths."""
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        key, separator, value = line.partition("=")
        if separator:
            parts = shlex.split(value, comments=False)
            values[key.strip()] = " ".join(parts)
    return values


def configure_data_access(root, value):
    """Allow only the configured data path through the system service sandbox."""
    path = Path(os.path.normpath(value))
    if not path.is_absolute() or path == Path("/") or any(c in value for c in "\n\r\0"):
        raise ValueError("Portal data directory must be an absolute non-root path")
    target = root / path.relative_to("/")
    if target.is_symlink():
        raise ValueError("Portal data directory must not be a symlink")
    created = not target.exists()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    dropin = root / "etc/systemd/system/openasrportal.service.d/20-data-directory.conf"
    dropin.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    # BindPaths also exposes an explicitly selected path below ProtectHome.
    dropin.write_text(
        '[Service]\nReadWritePaths="' + escaped + '"\nBindPaths="' + escaped + '"\n',
        encoding="utf-8",
    )
    if root == Path("/") and created:
        import pwd

        account = pwd.getpwnam("openasrportal")
        # Existing contents retain their ownership. Upgrade never recursively
        # takes over an arbitrary custom directory selected by an administrator.
        os.chown(target, account.pw_uid, account.pw_gid)


def configure(root, previous_version=""):
    directory = root / "var/lib/openasr/portal"
    legacy = root / "etc/openasrportal"
    for parent in (directory.parent, directory):
        if parent.is_symlink():
            raise ValueError("Portal installation paths must not be symlinks")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    environment = directory / "service.env"
    retained = (
        environment.exists()
        or (legacy / "service.env").exists()
        or (directory / "data/portal.db").exists()
    )
    for path in (environment, legacy / "service.env"):
        if path.is_symlink():
            raise ValueError("Portal environment must not be a symlink")
    if not environment.exists() and (legacy / "service.env").is_file():
        shutil.copy2(legacy / "service.env", environment)
    data = directory / "data"
    if data.is_symlink():
        raise ValueError(
            "Portal default data must not be a symlink; use an explicit custom data path"
        )
    old_data = root / "var/lib/openasrportal"
    if not environment.exists():
        values = {
            "OPENASRPORTAL_HOST": "127.0.0.1",
            "OPENASRPORTAL_PORT": "10087",
            "OPENASRPORTAL_DATA": "/var/lib/openasr/portal/data",
        }
        with os.fdopen(
            os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640), "w"
        ) as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    lines = environment.read_text(encoding="utf-8").splitlines()
    values = environment_values("\n".join(lines))
    migrate = values.get("OPENASRPORTAL_DATA") == "/var/lib/openasrportal"
    if migrate and not data.exists() and old_data.is_dir():
        if old_data.is_symlink() or any(path.is_symlink() for path in old_data.rglob("*")):
            raise ValueError("Legacy Portal data directory must not contain symlinks")
        # The package stops the service first. Retain the old copy for recovery.
        with tempfile.TemporaryDirectory(prefix=".data-migrating-", dir=directory) as temporary:
            staged = Path(temporary) / "data"
            shutil.copytree(old_data, staged)
            staged.rename(data)
    data.mkdir(exist_ok=True, mode=0o700)
    cleaned = [
        "OPENASRPORTAL_DATA=/var/lib/openasr/portal/data"
        if migrate and line.partition("=")[0].strip() == "OPENASRPORTAL_DATA"
        else line
        for line in lines
        if line.partition("=")[0].strip()
        not in {"OPENASRPORTAL_API_KEY", "OPENASRPORTAL_ADMIN_KEY"}
    ]
    if cleaned != lines:
        temporary = environment.with_suffix(".tmp")
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640), "w", encoding="utf-8"
        ) as stream:
            stream.write("\n".join(cleaned) + "\n")
        temporary.replace(environment)
    if (legacy / "service.env").is_file():
        # Preserve the old location for administrator recovery without retired keys.
        shutil.copy2(environment, legacy / "service.env")
    values = environment_values("\n".join(cleaned))
    configure_data_access(root, values.get("OPENASRPORTAL_DATA", "/var/lib/openasr/portal/data"))
    port = int(values.get("OPENASRPORTAL_PORT", "10087"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Portal port")
    host = values.get("OPENASRPORTAL_HOST", "127.0.0.1")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host:
        host = "[" + host + "]"
    url = f"http://{host}:{port}/admin"
    # Public launch address only; the service directory itself remains private.
    launch = root / "usr/share/openasrportal/admin.url"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text(url + "\n", encoding="utf-8")
    pending = directory / "pending-operation"
    upgrading = (
        pending.read_text().strip() == "upgrade" if pending.exists() else bool(previous_version)
    )
    state = "upgrade" if upgrading else "reinstall" if retained else "first-install"
    (directory / "installation.json").write_text(
        json.dumps({"schemaVersion": 1, "operation": state}) + "\n", encoding="utf-8"
    )
    pending.unlink(missing_ok=True)
    environment.chmod(0o600)
    # Retire only the known generated public credential handoff. Unknown files
    # are preserved but made private, never imported as authentication defaults.
    client = legacy / "client.json"
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
    parser.add_argument("--previous-version", default="")
    args = parser.parse_args()
    configure(args.root, args.previous_version)
