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
        parser.add_argument("--previous-version", default="")
        args = parser.parse_args(sys.argv[2:])
        configure(args.root, args.previous_version)
    elif sys.argv[1:2] == ["--provision-local-input"]:
        from openasrportal.entrypoints.provision import main as provision

        del sys.argv[1]
        provision()
    elif sys.argv[1:2] == ["--open-setup"]:
        from openasrportal.entrypoints.onboarding import main as onboarding

        del sys.argv[1]
        onboarding()
    elif sys.argv[1:2] == ["--migrate"]:
        from openasrportal.entrypoints.migrate import main as migrate

        del sys.argv[1]
        migrate()
    else:
        from openasrportal.entrypoints.cli import main as serve

        serve()


if __name__ == "__main__":
    main()
