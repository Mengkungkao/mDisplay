"""Find the desktop session (X11 or Wayland) whose screen mDisplay draws on.

Started by mFruit OS, mDisplay runs under whisplay-daemon's systemd service:
it has no DISPLAY, WAYLAND_DISPLAY or XAUTHORITY of its own. Environment
variables are only clues either way, so every candidate is verified by
actually connecting to it (X11: XOpenDisplay; Wayland: the compositor's
socket) before it is used.

Candidates, in order:
  1. an explicit choice (``--session :0`` / ``MDISPLAY_SESSION``)
  2. this process's own environment
  3. the environment of this user's processes in an active graphical login
     session (loginctl), e.g. gnome-shell: DISPLAY=:1, XAUTHORITY=...
  4. this user's other processes
  5. X11 and Wayland sockets found on disk

Nothing here needs root: only this user's own processes are read.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

X11_SOCKET_DIR = "/tmp/.X11-unix"
SESSION_KEYS = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE")
MAX_PROCESSES = 4000
MAX_ENVIRON = 256 * 1024


@dataclass
class Candidate:
    kind: str                    # "x11" | "wayland"
    display: str                 # ":1" | "wayland-0"
    env: dict                    # variables to export before SDL starts
    source: str                  # where the candidate came from
    session: str = ""            # loginctl session id, if known
    active: bool = False         # that session is the active one on its seat

    @property
    def key(self) -> tuple:
        return (self.kind, self.display, self.env.get("XAUTHORITY", ""))

    def describe(self) -> str:
        text = f"{self.kind} {self.display}"
        if self.env.get("XAUTHORITY"):
            text += f" (XAUTHORITY {self.env['XAUTHORITY']})"
        return text


@dataclass
class Check:
    candidate: Candidate
    ok: bool
    message: str


@dataclass
class SessionResult:
    chosen: Optional[Candidate]
    checks: list = field(default_factory=list)
    login_sessions: list = field(default_factory=list)
    problem: str = ""
    remedy: str = ""

    @property
    def headless(self) -> bool:
        return self.chosen is None and not self.checks


@dataclass
class LoginSession:
    id: str
    type: str
    active: bool
    remote: bool
    display: str
    state: str


# ------------------------------------------------------------------ sources

def login_sessions(uid: int, run: Callable = subprocess.run) -> list:
    """This user's graphical login sessions from loginctl ([] without systemd-logind)."""
    try:
        listing = run(["loginctl", "list-sessions", "--no-legend"], capture_output=True,
                      text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    sessions = []
    for line in (listing.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) != uid:
            continue
        try:
            shown = run(["loginctl", "show-session", parts[0], "-p", "Type", "-p", "Active",
                         "-p", "Remote", "-p", "Display", "-p", "State"],
                        capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            continue
        props = dict(item.split("=", 1) for item in (shown.stdout or "").splitlines()
                     if "=" in item)
        kind = props.get("Type", "")
        if kind not in ("x11", "wayland"):
            continue
        sessions.append(LoginSession(parts[0], kind, props.get("Active") == "yes",
                                     props.get("Remote") == "yes", props.get("Display", ""),
                                     props.get("State", "")))
    return sessions


def process_environments(uid: int, proc: str = "/proc") -> list:
    """[{pid, session, DISPLAY, ...}] for this user's processes that name a display."""
    found = []
    try:
        pids = [name for name in os.listdir(proc) if name.isdigit()]
    except OSError:
        return []
    for pid in pids[:MAX_PROCESSES]:
        base = os.path.join(proc, pid)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "environ"), "rb") as handle:
                raw = handle.read(MAX_ENVIRON)
        except OSError:
            continue
        values = {}
        for item in raw.split(b"\0"):
            key, sep, value = item.partition(b"=")
            if sep and key.decode("ascii", "replace") in SESSION_KEYS:
                values[key.decode("ascii")] = value.decode("utf-8", "replace")
        if not values.get("DISPLAY") and not values.get("WAYLAND_DISPLAY"):
            continue
        try:
            with open(os.path.join(base, "sessionid")) as handle:
                values["session"] = handle.read().strip()
        except OSError:
            values["session"] = ""
        values["pid"] = int(pid)
        found.append(values)
    return found


def runtime_dir(uid: int, env: dict, base: str = "/run/user") -> str:
    value = env.get("XDG_RUNTIME_DIR", "")
    if value and os.path.isdir(value):
        return value
    guess = os.path.join(base, str(uid))
    return guess if os.path.isdir(guess) else ""


def xauthority_candidates(uid: int, home: str, env: dict, envs: list, display: str,
                          run_base: str = "/run/user") -> list:
    """Possible cookie files for ``display``, most likely first."""
    paths = []
    if env.get("XAUTHORITY"):
        paths.append(env["XAUTHORITY"])
    for values in envs:
        if values.get("DISPLAY") == display and values.get("XAUTHORITY"):
            paths.append(values["XAUTHORITY"])
    run_dir = os.path.join(run_base, str(uid))
    paths += [os.path.join(run_dir, "gdm", "Xauthority"), os.path.join(home, ".Xauthority")]
    paths += sorted(glob.glob(os.path.join(run_dir, ".mutter-Xwaylandauth.*")))
    paths += sorted(glob.glob(os.path.join(run_dir, "xauth_*")))
    unique = []
    for path in paths:
        if path not in unique and os.path.isfile(path):
            unique.append(path)
    return unique


# ------------------------------------------------------------- verification

def _quiet_stderr():
    """Swap fd 2 for /dev/null (Xlib prints auth failures there); returns a restore function."""
    try:
        saved = os.dup(2)
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 2)
        os.close(null)
    except OSError:
        return lambda: None

    def restore():
        os.dup2(saved, 2)
        os.close(saved)
    return restore


def verify_x11(display: str, xauthority: str = "") -> tuple:
    """(ok, message): can this process open ``display`` with that cookie?"""
    name = ctypes.util.find_library("X11")
    if not name:
        return False, "libX11 is not installed, so X11 cannot be used"
    try:
        xlib = ctypes.CDLL(name)
    except OSError as exc:
        return False, f"cannot load libX11: {exc}"
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    saved = os.environ.get("XAUTHORITY")
    if xauthority:
        os.environ["XAUTHORITY"] = xauthority
    restore = _quiet_stderr()
    try:
        handle = xlib.XOpenDisplay(display.encode())
    finally:
        restore()
        if xauthority:
            if saved is None:
                os.environ.pop("XAUTHORITY", None)
            else:
                os.environ["XAUTHORITY"] = saved
    if not handle:
        if not os.path.exists(os.path.join(X11_SOCKET_DIR, "X" + display.lstrip(":").split(".")[0])):
            return False, f"no X server on {display}"
        return False, f"X server {display} refused the connection (authorization)"
    xlib.XCloseDisplay(handle)
    return True, f"connected to X server {display}"


def verify_wayland(display: str, run_dir: str) -> tuple:
    path = display if display.startswith("/") else os.path.join(run_dir, display)
    if not run_dir and not display.startswith("/"):
        return False, "XDG_RUNTIME_DIR is unknown"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(path)
    except OSError as exc:
        return False, f"cannot connect to Wayland compositor {path}: {exc.strerror or exc}"
    return True, f"connected to Wayland compositor {path}"


# ------------------------------------------------------------------ choice

def _x11(display: str, xauth: str, run_dir: str, source: str, session: str = "",
         active: bool = False) -> Candidate:
    env = {"DISPLAY": display}
    if xauth:
        env["XAUTHORITY"] = xauth
    if run_dir:
        env["XDG_RUNTIME_DIR"] = run_dir
    return Candidate("x11", display, env, source, session, active)


def _wayland(display: str, run_dir: str, source: str, session: str = "",
             active: bool = False) -> Candidate:
    env = {"WAYLAND_DISPLAY": display}
    if run_dir:
        env["XDG_RUNTIME_DIR"] = run_dir
    return Candidate("wayland", display, env, source, session, active)


def candidates(env: Optional[dict] = None, uid: Optional[int] = None, home: Optional[str] = None,
               explicit: str = "", run: Callable = subprocess.run, proc: str = "/proc",
               x11_dir: str = X11_SOCKET_DIR, run_base: str = "/run/user") -> tuple:
    """(candidates in preference order, login sessions)."""
    env = dict(os.environ if env is None else env)
    uid = os.getuid() if uid is None else uid
    home = home or env.get("HOME") or os.path.expanduser("~")
    run_dir = runtime_dir(uid, env, run_base)
    sessions = login_sessions(uid, run)
    envs = process_environments(uid, proc)
    active_ids = {s.id for s in sessions if s.active and not s.remote}
    graphical_ids = {s.id for s in sessions}
    found = []

    def add_x11(display, source, session="", active=False, xauth_env=None):
        cookies = xauthority_candidates(uid, home, xauth_env or {}, envs, display, run_base) or [""]
        for cookie in cookies:
            found.append(_x11(display, cookie, run_dir, source, session, active))

    if explicit:
        if explicit.startswith(":") or explicit.replace(".", "").isdigit():
            display = explicit if explicit.startswith(":") else ":" + explicit
            add_x11(display, "explicit", xauth_env=env)
        else:
            found.append(_wayland(explicit, run_dir, "explicit"))
        return _unique(found), sessions

    if env.get("DISPLAY"):
        add_x11(env["DISPLAY"], "environment", xauth_env=env)
    if env.get("WAYLAND_DISPLAY"):
        found.append(_wayland(env["WAYLAND_DISPLAY"], run_dir, "environment"))

    def rank(values):
        session = values.get("session", "")
        return (session not in active_ids, session not in graphical_ids, values["pid"])

    for values in sorted(envs, key=rank):
        session = values.get("session", "")
        active = session in active_ids
        source = "active login session" if active else (
            "login session" if session in graphical_ids else "user process")
        if values.get("DISPLAY"):
            add_x11(values["DISPLAY"], source, session, active, values)
        if values.get("WAYLAND_DISPLAY"):
            found.append(_wayland(values["WAYLAND_DISPLAY"], values.get("XDG_RUNTIME_DIR") or run_dir,
                                  source, session, active))
    for session in sessions:
        if session.display:
            add_x11(session.display, "loginctl", session.id, session.active)
    for path in sorted(glob.glob(os.path.join(x11_dir, "X*"))):
        number = os.path.basename(path)[1:]
        if number.isdigit():
            add_x11(":" + number, "X11 socket")
    if run_dir:
        for path in sorted(glob.glob(os.path.join(run_dir, "wayland-*"))):
            if not path.endswith(".lock"):
                found.append(_wayland(os.path.basename(path), run_dir, "Wayland socket"))
    return _unique(found), sessions


def _unique(found: list) -> list:
    seen, result = set(), []
    for candidate in found:
        if candidate.key not in seen:
            seen.add(candidate.key)
            result.append(candidate)
    return result


def find_session(env: Optional[dict] = None, explicit: str = "", uid: Optional[int] = None,
                 home: Optional[str] = None, run: Callable = subprocess.run, proc: str = "/proc",
                 verify_x: Callable = verify_x11, verify_w: Callable = verify_wayland,
                 prefer: str = "x11", x11_dir: str = X11_SOCKET_DIR,
                 run_base: str = "/run/user") -> SessionResult:
    """The first candidate that actually accepts a connection.

    X11 is preferred when both are offered (a Wayland desktop's XWayland):
    SDL 2 is most dependable there. ``prefer="wayland"`` reverses that.
    """
    found, sessions = candidates(env, uid, home, explicit, run, proc, x11_dir, run_base)
    found.sort(key=lambda c: (c.source != "explicit", not c.active and c.source != "environment",
                              c.kind != prefer))
    checks = []
    for candidate in found:
        if candidate.kind == "x11":
            ok, message = verify_x(candidate.display, candidate.env.get("XAUTHORITY", ""))
        else:
            ok, message = verify_w(candidate.display, candidate.env.get("XDG_RUNTIME_DIR", ""))
        checks.append(Check(candidate, ok, message))
        if ok:
            return SessionResult(candidate, checks, sessions)
    result = SessionResult(None, checks, sessions)
    if explicit:
        result.problem = f"The selected desktop session {explicit} cannot be opened."
        result.remedy = "Check that the desktop is running on it, or choose another session."
    elif not checks:
        result.problem = "No desktop session was found: this computer looks headless."
        result.remedy = ("Log in to the desktop (X11 or Wayland) on the HDMI screen as this "
                         "user, then try again.")
    else:
        result.problem = "A desktop session exists but mDisplay may not open it."
        result.remedy = ("Log in to the desktop as this user. An X server owned by someone "
                         "else needs its XAUTHORITY cookie; see docs/TROUBLESHOOTING.md.")
    return result


def apply(candidate: Candidate, environ: Optional[dict] = None) -> None:
    """Export the chosen session for SDL (before SDL_Init)."""
    environ = os.environ if environ is None else environ
    for key in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY"):
        if key not in candidate.env:
            environ.pop(key, None)
    for key, value in candidate.env.items():
        environ[key] = value
    if "SDL_VIDEODRIVER" not in environ:
        environ["SDL_VIDEODRIVER"] = "x11" if candidate.kind == "x11" else "wayland"
