#!/bin/sh
# Install hook. mFruit OS runs it on install, reinstall, update and downgrade,
# as the user, without a terminal; a non-zero exit keeps the previous version.
# Run it by hand on a desktop to set up the same way. It never uses sudo:
# system packages are named in the message instead.
#
#   SDL2 2.0.18+   the window and renderer   (apt: libsdl2-2.0-0)
#   Pillow 9.0+    LCD screens and text      (apt: python3-pil)
#   NumPy          procedural graphics       (apt: python3-numpy; else pip into a venv)
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
DATA="${WHISPLAY_OS_APP_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/mdisplay}"
VENV="$DATA/venv"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "mdisplay: Python 3.9 or newer is needed"; exit 1
fi
if ! err=$(python3 -c 'from app.display.sdl2 import SDL; SDL()' 2>&1); then
  echo "mdisplay: $(printf '%s\n' "$err" | tail -n 1)"
  echo "mdisplay: install SDL2 first: sudo apt install libsdl2-2.0-0"
  exit 1
fi
if ! python3 -c 'import PIL, sys; sys.exit(tuple(map(int, PIL.__version__.split(".")[:2])) < (9, 0))'; then
  echo "mdisplay: Pillow 9.0 or newer is needed: sudo apt install python3-pil"; exit 1
fi

PYTHON=python3
if ! python3 -c 'import numpy' 2>/dev/null; then
  if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import numpy' 2>/dev/null; then
    echo "mdisplay: NumPy is not installed system-wide; installing it into $VENV"
    mkdir -p "$DATA"
    if ! python3 -m venv --system-site-packages "$VENV" \
       || ! "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-input \
            --timeout 60 "numpy>=1.21"; then
      echo "mdisplay: could not install NumPy (no network?). Install it with:"
      echo "mdisplay:   sudo apt install python3-numpy"
      exit 1
    fi
  fi
  PYTHON="$VENV/bin/python"
fi
"$PYTHON" -c 'import numpy, PIL; from app.display.sdl2 import SDL; s = SDL(); print("mdisplay: dependencies ok: SDL", s.version_text, "NumPy", numpy.__version__, "Pillow", PIL.__version__)'
