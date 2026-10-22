#!/bin/sh
# Install hook. mFruit OS runs it on install, reinstall, update and downgrade,
# as the user, without a terminal; a non-zero exit keeps the previous version.
# Run it by hand on a desktop to set up the same way. It never uses sudo.
#
#   SDL2 2.0.18+   the window or direct HDMI output, the renderer   (Debian: libsdl2-2.0-0)
#   NumPy          procedural graphics                               (python3-numpy)
#   Pillow 9.0+    LCD screens and text                              (python3-pil)
#
# Whatever the system lacks is fetched without root from the system's own apt
# sources and unpacked into the data folder (app/deps.py); NumPy can also come
# from pip into a venv there. Nothing outside the data folder is changed.
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
DATA="${WHISPLAY_OS_APP_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/mdisplay}"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "mdisplay: Python 3.9 or newer is needed"; exit 1
fi
python3 -m app.deps ensure --data "$DATA"

# Report what run.sh will use.
if [ -f "$DATA/sysroot/env.sh" ]; then . "$DATA/sysroot/env.sh"; fi
PYTHON=python3
if [ -x "$DATA/venv/bin/python" ]; then PYTHON="$DATA/venv/bin/python"; fi
"$PYTHON" -c 'import numpy, PIL; from app.display.sdl2 import SDL; s = SDL(); print("mdisplay: dependencies ok: SDL", s.version_text, "NumPy", numpy.__version__, "Pillow", PIL.__version__)'
