"""Where mDisplay keeps its settings.

Under mFruit OS the data directory is ``WHISPLAY_OS_APP_DATA`` (kept across
updates and snapshotted before each one). Run by hand on a desktop it is
``$XDG_CONFIG_HOME/mdisplay`` (``~/.config/mdisplay``). ``MDISPLAY_DATA``
overrides both (tests, a second profile).
"""

from __future__ import annotations

import os

APP_ID = "mdisplay"


def managed(env=None) -> bool:
    """True when mFruit OS started this process (mfruit-run sets the app data dir)."""
    env = os.environ if env is None else env
    return bool(env.get("WHISPLAY_OS_APP_DATA"))


def data_dir(env=None) -> str:
    env = os.environ if env is None else env
    if env.get("MDISPLAY_DATA"):
        return env["MDISPLAY_DATA"]
    if env.get("WHISPLAY_OS_APP_DATA"):
        return env["WHISPLAY_OS_APP_DATA"]
    base = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"),
                                                      ".config")
    return os.path.join(base, APP_ID)


def settings_path(env=None) -> str:
    return os.path.join(data_dir(env), "settings.json")
