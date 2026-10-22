"""A small ctypes binding to SDL2: window, events, displays and the 2D renderer.

mDisplay draws through SDL2's renderer, which uses the GPU (OpenGL or
OpenGL ES) when the desktop offers it and SDL's own software renderer when
it does not. Only the calls mDisplay needs are bound, each with its exact C
signature: a wrong signature crashes the process instead of raising, so
every function is declared once, here.

SDL 2.0.18 or newer is required (SDL_RenderGeometry, float rectangles).
The library is the system's libSDL2 (Debian/Ubuntu: libsdl2-2.0-0);
``MDISPLAY_SDL2`` may name another copy.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import sys
from ctypes import POINTER, c_char_p, c_double, c_float, c_int, c_uint8, c_uint32, c_void_p
from typing import NamedTuple, Optional

MIN_VERSION = (2, 0, 18)

# SDL_Init
INIT_VIDEO = 0x00000020
INIT_EVENTS = 0x00004000

# SDL_WindowFlags
WINDOW_FULLSCREEN = 0x00000001
WINDOW_SHOWN = 0x00000004
WINDOW_HIDDEN = 0x00000008
WINDOW_BORDERLESS = 0x00000010
WINDOW_RESIZABLE = 0x00000020
WINDOW_MINIMIZED = 0x00000040
WINDOW_INPUT_FOCUS = 0x00000200
WINDOW_FULLSCREEN_DESKTOP = WINDOW_FULLSCREEN | 0x00001000
WINDOWPOS_CENTERED_MASK = 0x2FFF0000

# SDL_RendererFlags
RENDERER_SOFTWARE = 0x1
RENDERER_ACCELERATED = 0x2
RENDERER_PRESENTVSYNC = 0x4
RENDERER_TARGETTEXTURE = 0x8

# SDL_EventType
QUIT = 0x100
APP_TERMINATING = 0x101
DISPLAYEVENT = 0x150
WINDOWEVENT = 0x200
KEYDOWN = 0x300
KEYUP = 0x301
MOUSEMOTION = 0x400
MOUSEBUTTONDOWN = 0x401
RENDER_TARGETS_RESET = 0x2000
RENDER_DEVICE_RESET = 0x2001
USEREVENT = 0x8000

# SDL_WindowEventID
WINDOW_SHOWN_EVENT = 1
WINDOW_HIDDEN_EVENT = 2
WINDOW_EXPOSED = 3
WINDOW_MOVED = 4
WINDOW_RESIZED = 5
WINDOW_SIZE_CHANGED = 6
WINDOW_MINIMIZED_EVENT = 7
WINDOW_MAXIMIZED = 8
WINDOW_RESTORED = 9
WINDOW_FOCUS_GAINED = 12
WINDOW_FOCUS_LOST = 13
WINDOW_CLOSE = 14
WINDOW_DISPLAY_CHANGED = 18

# SDL_DisplayEventID
DISPLAY_CONNECTED = 2
DISPLAY_DISCONNECTED = 3

# SDL_BlendMode
BLEND_NONE = 0
BLEND_BLEND = 1
BLEND_ADD = 2
BLEND_MOD = 4
BLEND_MUL = 8

# SDL_BlendFactor / SDL_BlendOperation (for SDL_ComposeCustomBlendMode)
FACTOR_ZERO = 1
FACTOR_ONE = 2
FACTOR_SRC_COLOR = 3
FACTOR_ONE_MINUS_SRC_COLOR = 4
FACTOR_SRC_ALPHA = 5
FACTOR_ONE_MINUS_SRC_ALPHA = 6
OPERATION_ADD = 1

# SDL_TextureAccess / SDL_ScaleMode
TEXTUREACCESS_STATIC = 0
TEXTUREACCESS_TARGET = 2
SCALE_NEAREST = 0
SCALE_LINEAR = 1

# SDL_PIXELFORMAT_RGBA32: bytes R, G, B, A in memory, whatever the byte order.
PIXELFORMAT_ABGR8888 = 0x16762004
PIXELFORMAT_RGBA8888 = 0x16462004
PIXELFORMAT_RGBA32 = PIXELFORMAT_ABGR8888 if sys.byteorder == "little" else PIXELFORMAT_RGBA8888

# Keycodes (SDL_Keycode); scancode-based keys carry bit 30.
_SC = 1 << 30
K_BACKSPACE, K_TAB, K_RETURN, K_ESCAPE, K_SPACE = 8, 9, 13, 27, 32
K_F11 = _SC | 68
K_RIGHT, K_LEFT, K_DOWN, K_UP = _SC | 79, _SC | 80, _SC | 81, _SC | 82
K_HOME, K_PAGEUP, K_END, K_PAGEDOWN = _SC | 74, _SC | 75, _SC | 77, _SC | 78
K_KP_ENTER = _SC | 88
KMOD_SHIFT, KMOD_CTRL, KMOD_ALT, KMOD_GUI = 0x0003, 0x00C0, 0x0300, 0x0C00

EVENT_SIZE = 56


class SDLError(RuntimeError):
    """An SDL call failed; the message carries SDL_GetError()."""


class Version(ctypes.Structure):
    _fields_ = [("major", c_uint8), ("minor", c_uint8), ("patch", c_uint8)]


class Rect(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


class FRect(ctypes.Structure):
    _fields_ = [("x", c_float), ("y", c_float), ("w", c_float), ("h", c_float)]


class FPoint(ctypes.Structure):
    _fields_ = [("x", c_float), ("y", c_float)]


class DisplayMode(ctypes.Structure):
    _fields_ = [("format", c_uint32), ("w", c_int), ("h", c_int), ("refresh_rate", c_int),
                ("driverdata", c_void_p)]


class RendererInfo(ctypes.Structure):
    _fields_ = [("name", c_char_p), ("flags", c_uint32), ("num_texture_formats", c_uint32),
                ("texture_formats", c_uint32 * 16), ("max_texture_width", c_int),
                ("max_texture_height", c_int)]


class Event(NamedTuple):
    """One SDL event, decoded from the 56-byte SDL_Event union."""
    type: int
    window: int = 0          # windowID (window, key and mouse events)
    sub: int = 0             # window/display event ID, key state, mouse button
    data1: int = 0
    data2: int = 0
    sym: int = 0             # keycode
    mod: int = 0             # key modifiers
    repeat: int = 0
    code: int = 0            # user events
    display: int = 0         # display events


def decode_event(raw: bytes) -> Event:
    kind = struct.unpack_from("<I", raw, 0)[0]
    if kind == WINDOWEVENT:
        window, sub = struct.unpack_from("<IB", raw, 8)
        data1, data2 = struct.unpack_from("<ii", raw, 16)
        return Event(kind, window=window, sub=sub, data1=data1, data2=data2)
    if kind in (KEYDOWN, KEYUP):
        window, state, repeat = struct.unpack_from("<IBB", raw, 8)
        _scancode, sym, mod = struct.unpack_from("<iiH", raw, 16)
        return Event(kind, window=window, sub=state, sym=sym, mod=mod, repeat=repeat)
    if kind == DISPLAYEVENT:
        display, sub = struct.unpack_from("<IB", raw, 8)
        data1 = struct.unpack_from("<i", raw, 16)[0]
        return Event(kind, sub=sub, data1=data1, display=display)
    if kind == MOUSEMOTION:
        window = struct.unpack_from("<I", raw, 8)[0]
        x, y = struct.unpack_from("<ii", raw, 20)
        return Event(kind, window=window, data1=x, data2=y)
    if kind == MOUSEBUTTONDOWN:
        window = struct.unpack_from("<I", raw, 8)[0]
        button = struct.unpack_from("<B", raw, 16)[0]
        return Event(kind, window=window, sub=button)
    if kind >= USEREVENT:
        window, code = struct.unpack_from("<Ii", raw, 8)
        return Event(kind, window=window, code=code)
    return Event(kind)


# name -> (restype, argtypes)
_SIGNATURES = {
    "SDL_GetVersion": (None, [POINTER(Version)]),
    "SDL_Init": (c_int, [c_uint32]),
    "SDL_InitSubSystem": (c_int, [c_uint32]),
    "SDL_QuitSubSystem": (None, [c_uint32]),
    "SDL_Quit": (None, []),
    "SDL_GetError": (c_char_p, []),
    "SDL_ClearError": (None, []),
    "SDL_SetHint": (c_int, [c_char_p, c_char_p]),
    "SDL_GetNumVideoDrivers": (c_int, []),
    "SDL_GetVideoDriver": (c_char_p, [c_int]),
    "SDL_GetCurrentVideoDriver": (c_char_p, []),
    "SDL_GetNumVideoDisplays": (c_int, []),
    "SDL_GetDisplayName": (c_char_p, [c_int]),
    "SDL_GetDisplayBounds": (c_int, [c_int, POINTER(Rect)]),
    "SDL_GetCurrentDisplayMode": (c_int, [c_int, POINTER(DisplayMode)]),
    "SDL_CreateWindow": (c_void_p, [c_char_p, c_int, c_int, c_int, c_int, c_uint32]),
    "SDL_DestroyWindow": (None, [c_void_p]),
    "SDL_GetWindowID": (c_uint32, [c_void_p]),
    "SDL_GetWindowSize": (None, [c_void_p, POINTER(c_int), POINTER(c_int)]),
    "SDL_GetWindowPosition": (None, [c_void_p, POINTER(c_int), POINTER(c_int)]),
    "SDL_GetWindowDisplayIndex": (c_int, [c_void_p]),
    "SDL_GetWindowFlags": (c_uint32, [c_void_p]),
    "SDL_SetWindowFullscreen": (c_int, [c_void_p, c_uint32]),
    "SDL_SetWindowPosition": (None, [c_void_p, c_int, c_int]),
    "SDL_SetWindowSize": (None, [c_void_p, c_int, c_int]),
    "SDL_SetWindowMinimumSize": (None, [c_void_p, c_int, c_int]),
    "SDL_SetWindowTitle": (None, [c_void_p, c_char_p]),
    "SDL_SetWindowIcon": (None, [c_void_p, c_void_p]),
    "SDL_RaiseWindow": (None, [c_void_p]),
    "SDL_ShowCursor": (c_int, [c_int]),
    "SDL_EnableScreenSaver": (None, []),
    "SDL_DisableScreenSaver": (None, []),
    "SDL_CreateRGBSurfaceWithFormatFrom": (c_void_p, [c_void_p, c_int, c_int, c_int, c_int,
                                                      c_uint32]),
    "SDL_FreeSurface": (None, [c_void_p]),
    "SDL_PollEvent": (c_int, [c_void_p]),
    "SDL_WaitEventTimeout": (c_int, [c_void_p, c_int]),
    "SDL_PushEvent": (c_int, [c_void_p]),
    "SDL_RegisterEvents": (c_uint32, [c_int]),
    "SDL_GetNumRenderDrivers": (c_int, []),
    "SDL_GetRenderDriverInfo": (c_int, [c_int, POINTER(RendererInfo)]),
    "SDL_CreateRenderer": (c_void_p, [c_void_p, c_int, c_uint32]),
    "SDL_DestroyRenderer": (None, [c_void_p]),
    "SDL_GetRendererInfo": (c_int, [c_void_p, POINTER(RendererInfo)]),
    "SDL_GetRendererOutputSize": (c_int, [c_void_p, POINTER(c_int), POINTER(c_int)]),
    "SDL_SetRenderDrawColor": (c_int, [c_void_p, c_uint8, c_uint8, c_uint8, c_uint8]),
    "SDL_SetRenderDrawBlendMode": (c_int, [c_void_p, c_int]),
    "SDL_RenderClear": (c_int, [c_void_p]),
    "SDL_RenderFillRectF": (c_int, [c_void_p, POINTER(FRect)]),
    "SDL_RenderPresent": (None, [c_void_p]),
    "SDL_RenderFlush": (c_int, [c_void_p]),
    "SDL_RenderSetVSync": (c_int, [c_void_p, c_int]),
    "SDL_SetRenderTarget": (c_int, [c_void_p, c_void_p]),
    "SDL_RenderReadPixels": (c_int, [c_void_p, POINTER(Rect), c_uint32, c_void_p, c_int]),
    "SDL_RenderGeometry": (c_int, [c_void_p, c_void_p, c_void_p, c_int, c_void_p, c_int]),
    "SDL_RenderCopyExF": (c_int, [c_void_p, c_void_p, POINTER(Rect), POINTER(FRect), c_double,
                                  POINTER(FPoint), c_int]),
    "SDL_CreateTexture": (c_void_p, [c_void_p, c_uint32, c_int, c_int, c_int]),
    "SDL_DestroyTexture": (None, [c_void_p]),
    "SDL_UpdateTexture": (c_int, [c_void_p, POINTER(Rect), c_void_p, c_int]),
    "SDL_SetTextureBlendMode": (c_int, [c_void_p, c_int]),
    "SDL_SetTextureColorMod": (c_int, [c_void_p, c_uint8, c_uint8, c_uint8]),
    "SDL_SetTextureAlphaMod": (c_int, [c_void_p, c_uint8]),
    "SDL_SetTextureScaleMode": (c_int, [c_void_p, c_int]),
    "SDL_ComposeCustomBlendMode": (c_int, [c_int, c_int, c_int, c_int, c_int, c_int]),
}

LIBRARY_NAMES = ("libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so")


def find_library() -> Optional[str]:
    """The SDL2 shared library to load, or None."""
    override = os.environ.get("MDISPLAY_SDL2", "").strip()
    if override:
        return override
    found = ctypes.util.find_library("SDL2")
    if found:
        return found
    for name in LIBRARY_NAMES:
        try:
            ctypes.CDLL(name)
        except OSError:
            continue
        return name
    return None


class SDL:
    """The loaded library with typed functions as attributes (``sdl.SDL_Init``)."""

    def __init__(self, path: Optional[str] = None):
        path = path or find_library()
        if not path:
            raise SDLError("the SDL2 library was not found (Debian/Ubuntu: sudo apt install "
                           "libsdl2-2.0-0)")
        try:
            self.lib = ctypes.CDLL(path)
        except OSError as exc:
            raise SDLError(f"cannot load SDL2 from {path}: {exc}") from exc
        self.path = path
        version = Version()
        self.lib.SDL_GetVersion(ctypes.byref(version))
        self.version = (version.major, version.minor, version.patch)
        if self.version < MIN_VERSION:
            raise SDLError("SDL {} is too old: mDisplay needs SDL {} or newer".format(
                ".".join(map(str, self.version)), ".".join(map(str, MIN_VERSION))))
        for name, (restype, argtypes) in _SIGNATURES.items():
            try:
                function = getattr(self.lib, name)
            except AttributeError as exc:
                raise SDLError(f"{path} lacks {name}") from exc
            function.restype = restype
            function.argtypes = argtypes
            setattr(self, name, function)

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))

    def error(self) -> str:
        message = self.lib.SDL_GetError()
        return message.decode("utf-8", "replace") if message else "unknown SDL error"

    def check(self, result: int, what: str) -> int:
        """Raise SDLError for a negative SDL status."""
        if result is not None and result < 0:
            raise SDLError(f"{what}: {self.error()}")
        return result

    def text(self, value) -> str:
        return value.decode("utf-8", "replace") if value else ""

    def video_drivers(self) -> list:
        return [self.text(self.SDL_GetVideoDriver(i)) for i in range(self.SDL_GetNumVideoDrivers())]

    def render_drivers(self) -> list:
        """[(index, name, flags)] for every render driver this SDL was built with."""
        drivers = []
        for index in range(self.SDL_GetNumRenderDrivers()):
            info = RendererInfo()
            if self.SDL_GetRenderDriverInfo(index, ctypes.byref(info)) == 0:
                drivers.append((index, self.text(info.name), info.flags))
        return drivers

    def new_event_buffer(self):
        return (c_uint8 * EVENT_SIZE)()


def windowpos_centered(display_index: int) -> int:
    return WINDOWPOS_CENTERED_MASK | max(0, int(display_index))


def blend_screen(sdl: SDL) -> int:
    """A "screen" blend, src + dst*(1-src): bright layers combine without clipping.

    The source alpha is not used, so a screen-blended layer fades through its
    colour modulation. The software renderer refuses custom blend modes.
    """
    return sdl.SDL_ComposeCustomBlendMode(FACTOR_ONE, FACTOR_ONE_MINUS_SRC_COLOR, OPERATION_ADD,
                                          FACTOR_ZERO, FACTOR_ONE, OPERATION_ADD)
