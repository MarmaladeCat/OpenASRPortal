#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export OPENASRPORTAL_DATA="${OPENASRPORTAL_DATA:-$ROOT/runtime/data}"
export PYTHONDONTWRITEBYTECODE=1
exec "${OPENASRPORTAL_PYTHON:-$ROOT/.venv/bin/python}" -m openasrportal "$@"
