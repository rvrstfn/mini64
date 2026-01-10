#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

VENV_DIR=""
if [ -f ".venv/bin/activate" ]; then
  VENV_DIR=".venv"
elif [ -f "venv/bin/activate" ]; then
  VENV_DIR="venv"
fi

if [ -n "$VENV_DIR" ]; then
  # Use project venv when present (Pi setup).
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
fi

LOG_FILE="$REPO_DIR/mini64_x.log"
: > "$LOG_FILE"

PYTHON_BIN="python"
if [ -n "$VENV_DIR" ]; then
  PYTHON_BIN="$REPO_DIR/$VENV_DIR/bin/python"
fi

if ! "$PYTHON_BIN" -c "import pygame" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install pygame >>"$LOG_FILE" 2>&1
fi

exec startx "$PYTHON_BIN" "$REPO_DIR/mini64.py" -- :0 \
  >>"$LOG_FILE" 2>&1
