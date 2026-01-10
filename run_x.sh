#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
  # Use project venv when present (Pi setup).
  # shellcheck disable=SC1091
  . ".venv/bin/activate"
fi

LOG_FILE="$REPO_DIR/mini64_x.log"
: > "$LOG_FILE"

exec startx /usr/bin/python "$REPO_DIR/mini64.py" -- :0 \
  >>"$LOG_FILE" 2>&1
