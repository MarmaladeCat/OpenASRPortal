"""Start the same DB-authenticated Portal; never create credential config files."""

import os

os.environ.setdefault("OPENASRPORTAL_DATA", "/data")
os.execvp("python", ["python", "-m", "openasrportal"])
