#!/bin/zsh

ROOT="/Users/bradbanks/Downloads/chd-embroider-sewing-machine"
cd "$ROOT" || exit 1
exec "$ROOT/.venv/bin/python" "$ROOT/pes_viewer.py" "$@"
