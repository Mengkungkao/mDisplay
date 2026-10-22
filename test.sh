#!/bin/sh
# Smoke test ("test" in manifest.json): mFruit OS runs it after installing and
# before activating; a non-zero exit keeps the previous version. It imports the
# app, checks settings handling, draws every LCD screen and renders every scene
# offscreen (SDL's dummy video driver): it never opens a window, takes the LCD,
# or uses the network.
set -e
export PYTHONDONTWRITEBYTECODE=1   # leave the installed version folder as shipped
cd "$(dirname "$0")"
PYTHON=python3
VENV="${WHISPLAY_OS_APP_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/mdisplay}/venv"
if [ -x "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
fi
"$PYTHON" -m app.selftest
echo "mdisplay: test passed"
