"""Private installed runtime for service, installation setup and explicit migration."""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def main():
    if sys.argv[1:2] == ["--configure-installation"]:
        from configure import configure

        parser = argparse.ArgumentParser(
            description="Initialize Portal installation paths and network settings"
        )
        parser.add_argument("--root", type=Path, default=Path("/"))
        configure(parser.parse_args(sys.argv[2:]).root)
    elif sys.argv[1:2] == ["--migrate"]:
        from openasrportal.entrypoints.migrate import main as migrate

        del sys.argv[1]
        migrate()
    else:
        from openasrportal.entrypoints.cli import main as serve

        serve()


if __name__ == "__main__":
    main()
