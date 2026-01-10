#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  # Use project venv when present (Pi setup).
  # shellcheck disable=SC1091
  . ".venv/bin/activate"
fi

export MINI64_BACKEND=fb
python mini64.py "$@"
