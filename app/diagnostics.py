"""``--diagnose``: what the desktop and graphics offer mDisplay, and what is missing.

Everything is checked for real (a connection to the X server or Wayland
compositor, SDL started on it, a renderer created in a hidden window), and
reported with what to do about each problem. Environment variables are shown
but never taken as proof. Nothing here needs root or changes the system.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys

from . import __version__, paths


def _os_release() -> str:
    try:
        with open("/etc/os-release") as handle:
            values = dict(line.rstrip("\n").split("=", 1) for line in handle if "=" in line)
        return values.get("PRETTY_NAME", "").strip('"')
    except OSError:
        return ""


def _module(name: str):
    try:
        module = __import__(name)
        return getattr(module, "__version__", "installed"), ""
    except ImportError as exc:
        return None, str(exc)


def _gl_info() -> dict:
    """glxinfo -B (X11 only, optional): GPU and driver without root."""
    if not os.environ.get("DISPLAY") or not shutil.which("glxinfo"):
        return {}
    try:
        out = subprocess.run(["glxinfo", "-B"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    info = {}
    for line in out.splitlines():
        key, sep, value = line.partition(":")
        key = key.strip()
        if sep and key in ("OpenGL vendor string", "OpenGL renderer string", "OpenGL version string",
                           "OpenGL ES profile version string", "direct rendering"):
            info[key] = value.strip()
    return info


def _daemon_status() -> dict:
    socket_path = os.environ.get("WHISPLAY_DAEMON_SOCKET", "/tmp/whisplay-daemon.sock")
    result = {"socket": socket_path, "present": os.path.exists(socket_path), "reachable": False}
    if result["present"]:
        try:
            from .whisplay import request
            payload = request("health.ping", {}, timeout=2.0)
            result["reachable"] = True
            result["foreground"] = payload.get("foreground_app_id")
        except Exception as exc:
            result["error"] = str(exc)
    return result


def collect(env=None, open_display: bool = True) -> dict:
    """The full report as a dict (``--json`` prints it as is)."""
    from .display import session as sessions
    env = dict(os.environ if env is None else env)
    report = {"mdisplay": __version__, "python": platform.python_version(),
              "system": _os_release(), "machine": platform.machine(),
              "kernel": platform.release(), "problems": [], "notes": []}
    problems = report["problems"]
    report["environment"] = {k: env.get(k, "") for k in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
                                                         "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR",
                                                         "SDL_VIDEODRIVER")}
    report["mfruit_os"] = {"managed": paths.managed(env), "app_id": env.get("WHISPLAY_APP_ID", ""),
                           "home": env.get("MFRUIT_HOME", ""),
                           "settings": paths.settings_path(env),
                           "daemon": _daemon_status()}
    numpy_version, numpy_error = _module("numpy")
    pil_version, pil_error = _module("PIL")
    report["dependencies"] = {"numpy": numpy_version, "Pillow": pil_version}
    if numpy_version is None:
        problems.append(("NumPy is missing", "sudo apt install python3-numpy, or run install.sh"))
    if pil_version is None:
        problems.append(("Pillow is missing", "sudo apt install python3-pil"))
    from .display import sdl2
    try:
        sdl = sdl2.SDL()
        report["dependencies"]["SDL2"] = sdl.version_text
        report["sdl"] = {"library": sdl.path, "video_drivers": sdl.video_drivers(),
                         "render_drivers": [name for _i, name, _f in sdl.render_drivers()]}
    except sdl2.SDLError as exc:
        sdl = None
        report["dependencies"]["SDL2"] = None
        problems.append((str(exc), "Debian, Ubuntu, Raspberry Pi OS: sudo apt install libsdl2-2.0-0"))
    found = sessions.find_session(env, env.get("MDISPLAY_SESSION", ""))
    report["login_sessions"] = [vars(s) for s in found.login_sessions]
    report["session_checks"] = [{"session": c.candidate.describe(), "source": c.candidate.source,
                                 "ok": c.ok, "result": c.message} for c in found.checks]
    report["session"] = found.chosen.describe() if found.chosen else None
    report["headless"] = found.headless
    report["hdmi_direct"] = _kms_report()
    direct = next((c for c in report["hdmi_direct"] if c.get("connected") and c.get("external")), None)
    if found.chosen is None:
        if direct is not None:
            report["notes"].append(f"No desktop session: mDisplay draws directly on "
                                   f"{direct['connector']} (DRM/KMS, software rendering).")
        elif report["hdmi_direct"]:
            problems.append(("No desktop session, and no screen is connected to HDMI.",
                             "Connect a TV or monitor to HDMI (mDisplay then draws on it "
                             "directly), or log in to a desktop."))
        else:
            problems.append((found.problem, found.remedy))
    if sdl is not None and found.chosen is not None and open_display:
        sessions.apply(found.chosen)
        report.update(_probe_display(sdl))
        for problem in report.pop("display_problems", []):
            problems.append(problem)
        report["opengl"] = _gl_info()
    return report


def _kms_report() -> list:
    try:
        from .display import kms
        return kms.survey()
    except Exception as exc:          # diagnostics must not fail on an odd driver
        return [{"error": str(exc)}]


def _probe_display(sdl) -> dict:
    """Start SDL on the chosen session; list screens; try a renderer in a hidden window."""
    from .display.desktop import DesktopDisplay, DisplayUnavailable
    result = {"display_problems": []}
    display = DesktopDisplay(sdl=sdl, fullscreen=False, window_size=(64, 64), hidden=True)
    try:
        display.open()
    except DisplayUnavailable as exc:
        result["display_problems"].append((exc.problem, exc.remedy))
        result["renderer_attempts"] = [{"renderer": n, "error": e} for n, e in display.attempts]
        display.close()
        return result
    result["video_driver"] = display.video_driver
    result["displays"] = [info.as_dict() for info in display.displays_cache]
    result["renderer"] = {"name": display.driver, "accelerated": display.accelerated,
                          "max_texture": display.canvas.max_texture,
                          "custom_blend": display.canvas.screen_blend != 2}
    result["renderer_attempts"] = [{"renderer": n, "error": e} for n, e in display.attempts]
    if not display.accelerated:
        result["display_problems"].append((
            "Only software rendering is available: mDisplay works, more slowly",
            "Use quality Eco, or install the GPU's OpenGL driver for this desktop."))
    display.close()
    return result


def text_report(report: dict) -> str:
    lines = [f"mDisplay {report['mdisplay']} on {report['system'] or 'Linux'} "
             f"({report['machine']}, kernel {report['kernel']}), Python {report['python']}"]
    deps = report["dependencies"]
    lines.append("Dependencies: " + ", ".join(f"{k} {v or 'MISSING'}" for k, v in deps.items()))
    if report.get("sdl"):
        lines.append(f"SDL video drivers: {', '.join(report['sdl']['video_drivers'])}")
        lines.append(f"SDL render drivers: {', '.join(report['sdl']['render_drivers'])}")
    env = {k: v for k, v in report["environment"].items() if v}
    lines.append("Environment: " + (", ".join(f"{k}={v}" for k, v in env.items()) or "(no display variables)"))
    for s in report["login_sessions"]:
        lines.append(f"Login session {s['id']}: {s['type']}, {'active' if s['active'] else 'inactive'}"
                     f"{', remote' if s['remote'] else ''}")
    for check in report["session_checks"]:
        lines.append(f"  {'OK  ' if check['ok'] else 'FAIL'} {check['session']} "
                     f"[{check['source']}]: {check['result']}")
    lines.append(f"Desktop session: {report['session'] or 'none'}"
                 + (" (headless)" if report.get("headless") else ""))
    if report.get("video_driver"):
        lines.append(f"SDL video driver in use: {report['video_driver']}")
    for d in report.get("displays", []):
        rate = f" @ {d['refresh_hz']} Hz" if d["refresh_hz"] else ""
        output = f" {d['output']}" if d["output"] else ""
        lines.append(f"Screen {d['index']}:{output} \"{d['name']}\" {d['width']}x{d['height']}{rate} "
                     f"at ({d['x']},{d['y']})  [setting: {d['key']}]")
    renderer = report.get("renderer")
    if renderer:
        lines.append(f"Renderer: {renderer['name']} ({'GPU' if renderer['accelerated'] else 'software'}),"
                     f" max texture {renderer['max_texture']}")
    for attempt in report.get("renderer_attempts", []):
        if attempt["error"]:
            lines.append(f"  {attempt['renderer']} unavailable: {attempt['error']}")
    for key, value in (report.get("opengl") or {}).items():
        lines.append(f"{key}: {value}")
    for c in report.get("hdmi_direct", []):
        if "error" in c:
            lines.append(f"DRM {c.get('card', '')}: {c['error']}")
        else:
            modes = ", ".join(c["modes"][:4]) + (" …" if len(c["modes"]) > 4 else "")
            lines.append(f"DRM {c['card']} {c['connector']}: "
                         f"{'connected' if c['connected'] else 'not connected'}"
                         f"{'' if c['external'] else ' (built-in, not used)'}"
                         + (f"; modes {modes}" if c["connected"] else ""))
    for note in report.get("notes", []):
        lines.append(note)
    m = report["mfruit_os"]
    daemon = m["daemon"]
    lines.append(f"mFruit OS: {'started by mFruit OS' if m['managed'] else 'run by hand'}; "
                 f"whisplay-daemon {'reachable' if daemon.get('reachable') else 'not reachable'} "
                 f"({daemon['socket']}); settings {m['settings']}")
    if report["problems"]:
        lines.append("")
        lines.append("Problems:")
        for problem, remedy in report["problems"]:
            lines.append(f"  - {problem}")
            if remedy:
                lines.append(f"    what to do: {remedy}")
    else:
        lines.append("")
        lines.append("No problems found.")
    return "\n".join(lines)


def main(args) -> int:
    if getattr(args, "list_displays", False) and not getattr(args, "diagnose", False):
        report = collect()
        displays = report.get("displays", [])
        if not displays:
            print("No screens found.", *(f"{p}: {r}" for p, r in report["problems"]), sep="\n",
                  file=sys.stderr)
            return 3
        for d in displays:
            rate = f" @ {d['refresh_hz']} Hz" if d["refresh_hz"] else ""
            print(f"{d['key']}\t{d['width']}x{d['height']}{rate}\t{d['name']}")
        return 0
    report = collect()
    if getattr(args, "json", False):
        serializable = dict(report)
        serializable["problems"] = [{"problem": p, "remedy": r} for p, r in report["problems"]]
        print(json.dumps(serializable, indent=2))
    else:
        print(text_report(report))
    direct = any(c.get("connected") and c.get("external") for c in report.get("hdmi_direct", []))
    fatal = (report.get("session") is None and not direct) \
        or report["dependencies"].get("SDL2") is None or report["dependencies"].get("numpy") is None
    return 3 if fatal else 0
