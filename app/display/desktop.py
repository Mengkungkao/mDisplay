"""The desktop display host: one SDL window on a monitor of the desktop session.

This module owns everything about the window — the video subsystem,
display enumeration, the renderer (GPU first, SDL's software renderer as
the fallback), full screen, the cursor and the event queue — and nothing
else. It never touches the Whisplay HAT: that small LCD belongs to
whisplay-daemon. Full screen is SDL's "desktop" full screen, which covers
one monitor at its current mode and never changes the system's display
settings.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from . import sdl2
from .sdl2 import SDL, SDLError
from ..gfx.canvas import Canvas

log = logging.getLogger("mdisplay.display")

WAKE_CODE = 1
_XRANDR_LINE = re.compile(r"^(\S+) connected(?: primary)? (\d+)x(\d+)\+(-?\d+)\+(-?\d+)")


class DisplayUnavailable(Exception):
    """The window cannot be shown; ``remedy`` says what the user can do."""

    def __init__(self, problem: str, remedy: str = ""):
        super().__init__(problem)
        self.problem = problem
        self.remedy = remedy


@dataclass
class DisplayInfo:
    index: int
    name: str            # SDL's name (often the monitor's model)
    x: int
    y: int
    width: int
    height: int
    refresh: int         # Hz, 0 if unknown
    output: str = ""     # X11 output name (DP-0, HDMI-1) when xrandr can tell

    @property
    def key(self) -> str:
        """The stable name saved in the settings."""
        return self.output or f"display-{self.index}"

    @property
    def label(self) -> str:
        return self.output or self.name or f"Display {self.index + 1}"

    def describe(self) -> str:
        rate = f" · {self.refresh} Hz" if self.refresh else ""
        return f"{self.label} · {self.width}×{self.height}{rate}"

    def as_dict(self) -> dict:
        return {"index": self.index, "key": self.key, "name": self.name, "output": self.output,
                "x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "refresh_hz": self.refresh}


def xrandr_outputs(run=subprocess.run) -> list:
    """[(name, x, y, w, h)] for connected X11 outputs, [] when xrandr is unavailable."""
    if not os.environ.get("DISPLAY") or not shutil.which("xrandr"):
        return []
    try:
        result = run(["xrandr", "--query"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    outputs = []
    for line in (result.stdout or "").splitlines():
        match = _XRANDR_LINE.match(line)
        if match:
            name, w, h, x, y = match.group(1), *map(int, match.groups()[1:])
            outputs.append((name, x, y, w, h))
    return outputs


def pick_display(displays: list, key: str) -> tuple:
    """(display, notice): the chosen display; a notice when the saved one is missing.

    A missing explicit choice is never silent: the caller shows the notice.
    """
    if not displays:
        return None, ""
    if key and key != "auto":
        for info in displays:
            if key in (info.key, info.output, info.name, str(info.index)):
                return info, ""
        return displays[0], (f"Screen {key} is not connected; showing on {displays[0].label}. "
                             "Choose a screen in the settings.")
    return displays[0], ""


class DesktopDisplay:
    def __init__(self, sdl: Optional[SDL] = None, title: str = "mDisplay",
                 fullscreen: bool = True, display_key: str = "auto",
                 window_size: Optional[tuple] = None, renderer: str = "auto",
                 icon_rgba=None, hidden: bool = False):
        self.sdl = sdl
        self.hidden = hidden
        self.title = title
        self.fullscreen = fullscreen
        self.display_key = display_key
        self.window_size = window_size
        self.renderer_pref = renderer
        self.icon_rgba = icon_rgba
        self.window = None
        self.renderer = None
        self.window_id = 0
        self.canvas: Optional[Canvas] = None
        self.displays_cache: list = []
        self.display: Optional[DisplayInfo] = None
        self.notice = ""
        self.driver = ""
        self.video_driver = ""
        self.accelerated = False
        self.attempts: list = []          # (renderer, error) for diagnostics
        self.vsync = False
        self._event = None
        self._wake_type = 0
        self._wake = None
        self._video = False
        self.cursor_visible = True
        self.kms = None            # a kms.KmsOutput when frames go straight to HDMI (no desktop)
        self._scan = None          # scan_out: (frame buffer, its SDL surface, target surfaces)

    # -------------------------------------------------------------- open
    def open(self) -> "DesktopDisplay":
        try:
            self.sdl = self.sdl or SDL()
        except SDLError as exc:
            raise DisplayUnavailable(str(exc), "Install SDL2 (Debian, Ubuntu, Raspberry Pi OS: "
                                               "sudo apt install libsdl2-2.0-0).") from exc
        sdl = self.sdl
        for hint, value in ((b"SDL_RENDER_BATCHING", b"1"), (b"SDL_RENDER_SCALE_QUALITY", b"1"),
                            (b"SDL_NO_SIGNAL_HANDLERS", b"1"),
                            (b"SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", b"0"),
                            (b"SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", b"0"),
                            (b"SDL_APP_NAME", b"mDisplay")):
            sdl.SDL_SetHint(hint, value)
        if sdl.SDL_Init(sdl2.INIT_VIDEO | sdl2.INIT_EVENTS) != 0:
            message = sdl.error()
            raise DisplayUnavailable(f"The desktop's display cannot be opened: {message}",
                                     "Make sure the desktop is running on the screen and that "
                                     "this user is logged in to it (see mDisplay --diagnose).")
        self._video = True
        self.video_driver = sdl.text(sdl.SDL_GetCurrentVideoDriver())
        self._wake_type = sdl.SDL_RegisterEvents(1)
        self._event = sdl.new_event_buffer()
        self._wake = sdl.new_event_buffer()
        ctypes.memmove(self._wake, int(self._wake_type).to_bytes(4, "little"), 4)
        ctypes.memmove(ctypes.addressof(self._wake) + 12, WAKE_CODE.to_bytes(4, "little"), 4)
        self.displays_cache = self.list_displays()
        if not self.displays_cache:
            self.close()
            raise DisplayUnavailable("The desktop reports no screen.",
                                     "Connect and switch on the HDMI screen, then try again.")
        self.display, self.notice = pick_display(self.displays_cache, self.display_key)
        self._create_window()
        self._create_renderer()
        return self

    def list_displays(self) -> list:
        sdl = self.sdl
        outputs = xrandr_outputs() if self.video_driver == "x11" else []
        found = []
        for index in range(max(0, sdl.SDL_GetNumVideoDisplays())):
            bounds = sdl2.Rect()
            if sdl.SDL_GetDisplayBounds(index, ctypes.byref(bounds)) != 0:
                continue
            mode = sdl2.DisplayMode()
            refresh = 0
            if sdl.SDL_GetCurrentDisplayMode(index, ctypes.byref(mode)) == 0:
                refresh = mode.refresh_rate
            output = next((name for name, x, y, w, h in outputs
                           if (x, y, w, h) == (bounds.x, bounds.y, bounds.w, bounds.h)), "")
            found.append(DisplayInfo(index, sdl.text(sdl.SDL_GetDisplayName(index)), bounds.x,
                                     bounds.y, bounds.w, bounds.h, refresh, output))
        return found

    def _create_window(self) -> None:
        sdl = self.sdl
        info = self.display
        if self.window_size:
            w, h = self.window_size
        else:
            w, h = max(320, int(info.width * 0.6)), max(180, int(info.height * 0.6))
        flags = sdl2.WINDOW_RESIZABLE | (sdl2.WINDOW_HIDDEN if self.hidden else sdl2.WINDOW_SHOWN)
        position = sdl2.windowpos_centered(info.index)
        window = sdl.SDL_CreateWindow(self.title.encode(), position, position, int(w), int(h), flags)
        if not window:
            message = sdl.error()
            raise DisplayUnavailable(f"The window could not be created: {message}",
                                     "Check the desktop session and its graphics driver "
                                     "(mDisplay --diagnose).")
        self.window = window
        self.window_id = sdl.SDL_GetWindowID(window)
        sdl.SDL_SetWindowMinimumSize(window, 160, 90)
        self._set_icon()
        if self.fullscreen and not self.hidden:
            self.set_fullscreen(True)

    def _set_icon(self) -> None:
        if self.icon_rgba is None:
            return
        try:
            import numpy as np
            pixels = np.ascontiguousarray(self.icon_rgba, np.uint8)
            h, w = pixels.shape[:2]
            surface = self.sdl.SDL_CreateRGBSurfaceWithFormatFrom(
                pixels.ctypes.data, w, h, 32, w * 4, sdl2.PIXELFORMAT_RGBA32)
            if surface:
                self.sdl.SDL_SetWindowIcon(self.window, surface)
                self.sdl.SDL_FreeSurface(surface)
        except Exception as exc:          # the icon is cosmetic
            log.debug("window icon not set: %s", exc)

    def _create_renderer(self) -> None:
        sdl = self.sdl
        drivers = sdl.render_drivers()
        if self.renderer_pref in ("auto", "", None):
            order = [d for d in drivers if d[1] != "software"] + [d for d in drivers if d[1] == "software"]
        else:
            order = [d for d in drivers if d[1] == self.renderer_pref]
            if not order:
                raise DisplayUnavailable(f"Renderer {self.renderer_pref} is not available.",
                                         "Available: " + ", ".join(d[1] for d in drivers))
        for index, name, _flags in order:
            flags = sdl2.RENDERER_TARGETTEXTURE
            flags |= sdl2.RENDERER_SOFTWARE if name == "software" else sdl2.RENDERER_ACCELERATED
            renderer = sdl.SDL_CreateRenderer(self.window, index, flags)
            if not renderer:
                self.attempts.append((name, sdl.error()))
                log.info("renderer %s unavailable: %s", name, sdl.error())
                sdl.SDL_ClearError()
                continue
            info = sdl2.RendererInfo()
            sdl.SDL_GetRendererInfo(renderer, ctypes.byref(info))
            self.renderer = renderer
            self.driver = sdl.text(info.name) or name
            self.accelerated = bool(info.flags & sdl2.RENDERER_ACCELERATED)
            self.attempts.append((name, ""))
            self.canvas = Canvas(sdl, renderer, self.driver, self.accelerated,
                                 min(info.max_texture_width or 16384,
                                     info.max_texture_height or 16384))
            log.info("renderer %s (%s) on %s", self.driver,
                     "GPU" if self.accelerated else "software", self.video_driver)
            return
        tried = "; ".join(f"{name}: {error}" for name, error in self.attempts)
        raise DisplayUnavailable(f"No renderer could start ({tried}).",
                                 "Check the graphics driver (mDisplay --diagnose).")

    # ------------------------------------------------------------ control
    @property
    def size(self) -> tuple:
        """The size scenes draw at (with ``kms``, possibly smaller than the HDMI mode)."""
        if self.canvas is None:
            return 0, 0
        return self.canvas.refresh_size()

    @property
    def output_size(self) -> tuple:
        """The size of the picture on the screen: the window, or the HDMI mode."""
        if self.kms is not None:
            return self.kms.size
        return self.size

    def scan_out(self, address: int, pitch: int) -> None:
        """Write the finished frame into a mapped KMS frame buffer of ``kms.size``
        (XRGB8888, which is SDL's ARGB8888), scaled up with linear filtering when it
        was drawn smaller: one read of the small frame and one stretch, no copies."""
        w, h = self.size
        ow, oh = self.kms.size
        if (w, h) == (ow, oh):
            self.canvas.read_into(address, pitch)
            return
        sdl = self.sdl
        if self._scan is None or self._scan[3] != (w, h, ow, oh):
            self._free_scan()
            frame = (ctypes.c_uint8 * (w * h * 4))()
            surface = sdl.SDL_CreateRGBSurfaceWithFormatFrom(ctypes.addressof(frame), w, h, 32,
                                                             w * 4, sdl2.PIXELFORMAT_ARGB8888)
            if not surface:
                raise sdl2.SDLError(f"frame surface: {sdl.error()}")
            self._scan = (frame, surface, {}, (w, h, ow, oh))
        frame, surface, targets, _sizes = self._scan
        target = targets.get((address, pitch))
        if target is None:
            target = sdl.SDL_CreateRGBSurfaceWithFormatFrom(address, ow, oh, 32, pitch,
                                                            sdl2.PIXELFORMAT_ARGB8888)
            if not target:
                raise sdl2.SDLError(f"frame buffer surface: {sdl.error()}")
            targets[(address, pitch)] = target
        self.canvas.read_into(ctypes.addressof(frame), w * 4)
        sdl.check(sdl.SDL_SoftStretchLinear(surface, None, target, None), "scale up")

    def _free_scan(self) -> None:
        if self._scan is not None:
            _frame, surface, targets, _sizes = self._scan
            for target in targets.values():
                self.sdl.SDL_FreeSurface(target)
            self.sdl.SDL_FreeSurface(surface)
            self._scan = None

    def set_vsync(self, on: bool) -> bool:
        if self.renderer is None or self.kms is not None:
            return False          # KMS output waits for the vertical blank itself
        ok = self.sdl.SDL_RenderSetVSync(self.renderer, 1 if on else 0) == 0
        self.vsync = on if ok else False
        return ok

    def set_fullscreen(self, on: bool) -> bool:
        if self.kms is not None:
            return True           # straight to HDMI is always the whole screen
        if self.window is None:
            return False
        flags = sdl2.WINDOW_FULLSCREEN_DESKTOP if on else 0
        if self.sdl.SDL_SetWindowFullscreen(self.window, flags) != 0:
            log.warning("full screen %s failed: %s", "on" if on else "off", self.sdl.error())
            return False
        self.fullscreen = on
        self.show_cursor(not on)
        return True

    def toggle_fullscreen(self) -> bool:
        self.set_fullscreen(not self.fullscreen)
        return self.fullscreen

    def move_to(self, key: str) -> str:
        """Show the window on another display; returns a notice ('' when done)."""
        if self.kms is not None:
            return "The new screen is used the next time mDisplay opens."
        self.displays_cache = self.list_displays()
        info, notice = pick_display(self.displays_cache, key)
        if info is None or notice:
            return notice or "No screen found."
        self.display_key = key
        self.display = info
        was_full = self.fullscreen
        if was_full:
            self.set_fullscreen(False)
        position = sdl2.windowpos_centered(info.index)
        self.sdl.SDL_SetWindowPosition(self.window, position, position)
        if was_full:
            self.set_fullscreen(True)
        return ""

    def current_display_index(self) -> int:
        if self.window is None:
            return -1
        return self.sdl.SDL_GetWindowDisplayIndex(self.window)

    def show_cursor(self, visible: bool) -> None:
        if self._video and visible != self.cursor_visible:
            self.sdl.SDL_ShowCursor(1 if visible else 0)
            self.cursor_visible = visible

    def allow_screensaver(self, allow: bool) -> None:
        if self._video:
            (self.sdl.SDL_EnableScreenSaver if allow else self.sdl.SDL_DisableScreenSaver)()

    def raise_window(self) -> None:
        if self.window is not None:
            self.sdl.SDL_RaiseWindow(self.window)

    def window_flags(self) -> int:
        return self.sdl.SDL_GetWindowFlags(self.window) if self.window else 0

    # ------------------------------------------------------------- events
    def events(self, timeout: float = 0.0) -> list:
        """Events now; with ``timeout`` > 0, wait up to that many seconds for the first."""
        sdl, buf = self.sdl, self._event
        if buf is None:
            return []
        found = []
        if timeout > 0:
            if sdl.SDL_WaitEventTimeout(buf, max(1, int(timeout * 1000))):
                found.append(sdl2.decode_event(bytes(buf)))
        while sdl.SDL_PollEvent(buf):
            found.append(sdl2.decode_event(bytes(buf)))
        return found

    def wake(self) -> None:
        """Interrupt an ``events(timeout)`` wait; safe from any thread."""
        if self._wake is not None and self._video:
            self.sdl.SDL_PushEvent(self._wake)

    def is_wake(self, event) -> bool:
        return event.type == self._wake_type and self._wake_type != 0

    # -------------------------------------------------------------- close
    def close(self) -> None:
        sdl = self.sdl
        self._free_scan()
        if self.kms is not None:
            self.kms.close()      # the console comes back on the HDMI screen
            self.kms = None
        if self.canvas is not None:
            self.canvas.destroy_all()
            self.canvas = None
        if self.renderer is not None:
            sdl.SDL_DestroyRenderer(self.renderer)
            self.renderer = None
        if self.window is not None:
            sdl.SDL_DestroyWindow(self.window)
            self.window = None
        if self._video:
            self.show_cursor(True)
            sdl.SDL_QuitSubSystem(sdl2.INIT_VIDEO | sdl2.INIT_EVENTS)
            sdl.SDL_Quit()
            self._video = False
        self._event = None
