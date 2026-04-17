#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
exec "$ROOT/.venv/bin/python" "$ROOT/pes_viewer.py" "$@"
