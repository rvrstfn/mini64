#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/mini64_kms_safe.log"

# Redirect logs so we can see if it crashes.
exec > "$LOG_FILE" 2>&1

echo "--- KMS SAFE LAUNCH STARTED $(date) ---"

cleanup() {
  setterm -cursor on || true
  echo "Exited."
}
trap cleanup EXIT

setterm -cursor off || true

# Direct KMS/DRM output, no X11.
export SDL_VIDEODRIVER=kmsdrm
# Force software rendering and avoid vsync stalls.
export SDL_RENDER_DRIVER=software
export SDL_RENDER_VSYNC=0
export SDL_VIDEO_DOUBLE_BUFFER=1
# Audio off for stability.
export SDL_AUDIODRIVER=dummy
# Use raw input events.
export SDL_IN_NODEVICE=1

cd "$REPO_DIR"

echo "Launching Python..."
/usr/bin/python3 -u mini64.py
