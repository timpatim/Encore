#!/usr/bin/env bash
# Encore - starts the local server and opens the interface (http://127.0.0.1:8190) (Linux).
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m encore "$@"
fi
if [ -n "$CONDA_PREFIX" ]; then
  exec python -m encore "$@"
fi
echo "No environment found: run ./install.sh first (venv),"
echo "or activate the conda environment (conda activate encore), then run this file again."
exit 1
