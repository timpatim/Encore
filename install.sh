#!/usr/bin/env bash
# Encore - creates the Python environment (.venv) next to this file (Linux).
# Needs Python 3.10 or newer (python3) with the venv module (Debian/Ubuntu: sudo apt install python3-venv).
set -e
cd "$(dirname "$0")"
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python not found. Install Python 3.10 or newer, or use conda: see README.md"
  exit 1
fi
echo "Creating the .venv environment with $PY ..."
"$PY" -m venv .venv || { echo "Could not create the venv (python3-venv package missing?)"; exit 1; }
.venv/bin/python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10 or newer is required'"
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
echo
echo "Environment ready. Run ./encore.sh"
