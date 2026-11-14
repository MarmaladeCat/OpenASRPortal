"""Default persistent paths shared by foreground and installed service entry points."""

import os
from pathlib import Path


def state_directory():
    base = (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OpenASR"
            if os.name == "nt" else Path("/var/lib/OpenASR"))
    return Path(os.environ.get("OPENASR_DATA_ROOT", base)).expanduser() / "portal"


def data_directory():
    return Path(os.environ.get("OPENASRPORTAL_DATA", state_directory() / "data")).expanduser()
