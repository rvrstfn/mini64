#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/mini64_kms.log"

# Redirect logs so we can see if it crashes.
exec > "$LOG_FILE" 2>&1

echo "--- KMS LAUNCH STARTED $(date) ---"

# Always restore the cursor on exit.
cleanup() {
  setterm -cursor on || true
  echo "Exited."
}
trap cleanup EXIT

# Stop the blinking cursor on the command line.
setterm -cursor off || true

# Direct KMS/DRM output, no X11.
export SDL_VIDEODRIVER=kmsdrm
# Audio off for stability.
export SDL_AUDIODRIVER=dummy
# Use raw input events.
export SDL_IN_NODEVICE=1

cd "$REPO_DIR"

echo "Launching Python..."
/usr/bin/python3 -u mini64.py
