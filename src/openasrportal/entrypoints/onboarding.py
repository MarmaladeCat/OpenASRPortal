"""Open local first-time setup only when the running Portal is not initialized."""

import argparse
import configparser
import json
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def setup_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Invalid Portal management URL")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    with urlopen(origin + "/v1/admin/auth/status", timeout=2) as response:
        status = json.load(response)
    return None if status["initialized"] else origin + "/admin/setup"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:10087/admin")
    parser.add_argument("--url-file", type=Path)
    args = parser.parse_args()
    url = args.url
    if args.url_file:
        text = args.url_file.read_text(encoding="utf-8-sig").strip()
        if text.startswith("[InternetShortcut]"):
            shortcut = configparser.ConfigParser(interpolation=None)
            shortcut.read_string(text)
            url = shortcut["InternetShortcut"]["URL"]
        else:
            url = text
    deadline = time.monotonic() + 20
    while True:
        try:
            destination = setup_url(url)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    if destination:
        webbrowser.open(destination)


if __name__ == "__main__":
    main()
