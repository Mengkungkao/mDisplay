#!/bin/sh
# Entrypoint. mFruit OS starts it through mfruit-run with the working directory
# set to the active version and WHISPLAY_APP_ID / WHISPLAY_OS_APP_DATA set: the
# scenes go to the desktop's screen (HDMI), the remote control to the Whisplay
# LCD. Run it by hand on a desktop for the window alone (./run.sh --help).
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
PYTHON=python3
# install.sh makes a venv only when NumPy had to come from pip.
VENV="${WHISPLAY_OS_APP_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/mdisplay}/venv"
if [ -x "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
fi
exec "$PYTHON" -m app.main "$@"
