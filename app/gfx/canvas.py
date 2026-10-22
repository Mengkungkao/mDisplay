"""The drawing surface scenes use: textures, sprite batches, meshes and fills.

A thin layer over SDL2's renderer (``display/sdl2.py``). Scenes never call
SDL themselves, so they do not know whether the frame is drawn by the GPU
(OpenGL / OpenGL ES) or by SDL's software renderer.

Coordinates are floats in output pixels. The GPU renderers honour
sub-pixel positions, which keeps very slow drifts smooth; the software
renderer rounds to whole pixels.
"""

from __future__ import annotations

import ctypes
import logging
from contextlib import contextmanager
from typing import Optional

import numpy as np

from ..display import sdl2
from ..display.sdl2 import FPoint, FRect, Rect

log = logging.getLogger("mdisplay.canvas")

BLEND = sdl2.BLEND_BLEND
ADD = sdl2.BLEND_ADD
MOD = sdl2.BLEND_MOD
NONE = sdl2.BLEND_NONE

# SDL_Vertex: SDL_FPoint position, SDL_Color color, SDL_FPoint tex_coord (20 bytes).
VERTEX = np.dtype([("x", "<f4"), ("y", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1"),
                   ("a", "u1"), ("u", "<f4"), ("v", "<f4")])
assert VERTEX.itemsize == 20


class Texture:
    """A GPU (or software) texture owned by one Canvas."""

    __slots__ = ("canvas", "ptr", "width", "height", "name", "blend", "_mod", "target")

    def __init__(self, canvas: "Canvas", ptr: int, width: int, height: int, name: str,
                 blend: int, target: bool = False):
        self.canvas = canvas
        self.ptr = ptr
        self.width = width
        self.height = height
        self.name = name
        self.blend = blend
        self._mod = None
        self.target = target

    @property
    def alive(self) -> bool:
        return self.ptr is not None

    def set_blend(self, blend: int) -> None:
        if blend != self.blend and self.ptr is not None:
            self.canvas.sdl.SDL_SetTextureBlendMode(self.ptr, blend)
            self.blend = blend

    def modulate(self, color=(255, 255, 255), alpha: int = 255) -> None:
        key = (int(color[0]), int(color[1]), int(color[2]), int(alpha))
        if key != self._mod and self.ptr is not None:
            sdl = self.canvas.sdl
            sdl.SDL_SetTextureColorMod(self.ptr, *_clamp3(key[:3]))
            sdl.SDL_SetTextureAlphaMod(self.ptr, max(0, min(255, key[3])))
            self._mod = key

    def destroy(self) -> None:
        if self.ptr is not None:
            self.canvas._forget(self)
            self.canvas.sdl.SDL_DestroyTexture(self.ptr)
            self.ptr = None

    def __repr__(self) -> str:
        return f"<Texture {self.name} {self.width}x{self.height}{' dead' if self.ptr is None else ''}>"


def _clamp3(rgb):
    return tuple(max(0, min(255, int(v))) for v in rgb)


class Canvas:
    def __init__(self, sdl: sdl2.SDL, renderer: int, driver: str = "", accelerated: bool = False,
                 max_texture: int = 0):
        self.sdl = sdl
        self.renderer = renderer
        self.driver = driver
        self.accelerated = accelerated
        self.max_texture = max_texture or 16384
        self.width = 0
        self.height = 0
        self._textures: set = set()
        self._dst = FRect()
        self._src = Rect()
        self._center = FPoint()
        self._target: Optional[Texture] = None
        self.draw_calls = 0
        self.screen_blend = ADD
        self.refresh_size()
        self._detect_screen_blend()

    # ------------------------------------------------------------- state
    def refresh_size(self) -> tuple:
        w, h = ctypes.c_int(), ctypes.c_int()
        if self.sdl.SDL_GetRendererOutputSize(self.renderer, ctypes.byref(w), ctypes.byref(h)) == 0:
            self.width, self.height = w.value, h.value
        return self.width, self.height

    @property
    def size(self) -> tuple:
        return self.width, self.height

    @property
    def live_textures(self) -> int:
        return len(self._textures)

    def _detect_screen_blend(self) -> None:
        mode = sdl2.blend_screen(self.sdl)
        probe = self.sdl.SDL_CreateTexture(self.renderer, sdl2.PIXELFORMAT_RGBA32,
                                           sdl2.TEXTUREACCESS_STATIC, 1, 1)
        if not probe:
            return
        try:
            if self.sdl.SDL_SetTextureBlendMode(probe, mode) == 0:
                self.screen_blend = mode
        finally:
            self.sdl.SDL_DestroyTexture(probe)
            self.sdl.SDL_ClearError()

    def _forget(self, texture: Texture) -> None:
        self._textures.discard(texture)

    # ----------------------------------------------------------- textures
    def texture(self, rgba: np.ndarray, blend: int = BLEND, linear: bool = True,
                name: str = "") -> Texture:
        """Upload an (H, W, 4) uint8 RGBA array (straight alpha)."""
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError(f"texture {name}: expected (H, W, 4), got {rgba.shape}")
        h, w = rgba.shape[:2]
        if w > self.max_texture or h > self.max_texture:
            raise ValueError(f"texture {name} {w}x{h} exceeds the renderer's {self.max_texture}")
        ptr = self.sdl.SDL_CreateTexture(self.renderer, sdl2.PIXELFORMAT_RGBA32,
                                         sdl2.TEXTUREACCESS_STATIC, w, h)
        if not ptr:
            raise sdl2.SDLError(f"cannot create texture {name} {w}x{h}: {self.sdl.error()}")
        self.sdl.check(self.sdl.SDL_UpdateTexture(ptr, None, rgba.ctypes.data, w * 4),
                       f"upload {name}")
        self.sdl.SDL_SetTextureBlendMode(ptr, blend)
        self.sdl.SDL_SetTextureScaleMode(ptr, sdl2.SCALE_LINEAR if linear else sdl2.SCALE_NEAREST)
        tex = Texture(self, ptr, w, h, name, blend)
        self._textures.add(tex)
        return tex

    def update(self, texture: Texture, rgba: np.ndarray) -> None:
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
        if rgba.shape[:2] != (texture.height, texture.width):
            raise ValueError("update: size differs from the texture")
        self.sdl.check(self.sdl.SDL_UpdateTexture(texture.ptr, None, rgba.ctypes.data,
                                                  texture.width * 4), f"update {texture.name}")

    def target(self, width: int, height: int, name: str = "target", blend: int = BLEND) -> Texture:
        """A texture scenes can render into (``with canvas.into(tex):``)."""
        ptr = self.sdl.SDL_CreateTexture(self.renderer, sdl2.PIXELFORMAT_RGBA32,
                                         sdl2.TEXTUREACCESS_TARGET, int(width), int(height))
        if not ptr:
            raise sdl2.SDLError(f"cannot create render target {width}x{height}: {self.sdl.error()}")
        self.sdl.SDL_SetTextureBlendMode(ptr, blend)
        self.sdl.SDL_SetTextureScaleMode(ptr, sdl2.SCALE_LINEAR)
        tex = Texture(self, ptr, int(width), int(height), name, blend, target=True)
        self._textures.add(tex)
        return tex

    @contextmanager
    def into(self, texture: Optional[Texture]):
        previous = self._target
        self._set_target(texture)
        try:
            yield texture
        finally:
            self._set_target(previous)

    def _set_target(self, texture: Optional[Texture]) -> None:
        self.sdl.check(self.sdl.SDL_SetRenderTarget(self.renderer, texture.ptr if texture else None),
                       "set render target")
        self._target = texture

    def destroy_all(self) -> None:
        for texture in list(self._textures):
            texture.destroy()

    # ------------------------------------------------------------ drawing
    def clear(self, color=(0, 0, 0), alpha: int = 255) -> None:
        r, g, b = _clamp3(color)
        self.sdl.SDL_SetRenderDrawColor(self.renderer, r, g, b, max(0, min(255, int(alpha))))
        self.sdl.SDL_RenderClear(self.renderer)
        self.draw_calls += 1

    def fill(self, x: float, y: float, w: float, h: float, color=(0, 0, 0), alpha: int = 255,
             blend: int = BLEND) -> None:
        r, g, b = _clamp3(color)
        self.sdl.SDL_SetRenderDrawBlendMode(self.renderer, blend)
        self.sdl.SDL_SetRenderDrawColor(self.renderer, r, g, b, max(0, min(255, int(alpha))))
        dst = self._dst
        dst.x, dst.y, dst.w, dst.h = x, y, w, h
        self.sdl.SDL_RenderFillRectF(self.renderer, ctypes.byref(dst))
        self.draw_calls += 1

    def dim(self, amount: float) -> None:
        """Darken everything drawn so far by ``amount`` (0 = unchanged, 1 = black)."""
        if amount > 0.002:
            target = self._target
            w, h = (target.width, target.height) if target else (self.width, self.height)
            self.fill(0, 0, w, h, (0, 0, 0), int(round(255 * min(1.0, amount))), BLEND)

    def image(self, texture: Texture, x: float, y: float, w: Optional[float] = None,
              h: Optional[float] = None, angle: float = 0.0, center: Optional[tuple] = None,
              color=(255, 255, 255), alpha: int = 255, src: Optional[tuple] = None,
              blend: Optional[int] = None) -> None:
        """Draw ``texture`` with its top-left at (x, y); ``angle`` in degrees, clockwise."""
        if texture.ptr is None:
            return
        if blend is not None:
            texture.set_blend(blend)
        texture.modulate(color, alpha)
        dst = self._dst
        dst.x, dst.y = x, y
        dst.w = texture.width if w is None else w
        dst.h = texture.height if h is None else h
        src_ptr = None
        if src is not None:
            s = self._src
            s.x, s.y, s.w, s.h = (int(v) for v in src)
            src_ptr = ctypes.byref(s)
        center_ptr = None
        if center is not None:
            c = self._center
            c.x, c.y = center
            center_ptr = ctypes.byref(c)
        self.sdl.SDL_RenderCopyExF(self.renderer, texture.ptr, src_ptr, ctypes.byref(dst),
                                   float(angle), center_ptr, 0)
        self.draw_calls += 1

    def centered(self, texture: Texture, cx: float, cy: float, w: float, h: float,
                 angle: float = 0.0, color=(255, 255, 255), alpha: int = 255,
                 blend: Optional[int] = None) -> None:
        self.image(texture, cx - w / 2.0, cy - h / 2.0, w, h, angle, None, color, alpha,
                   blend=blend)

    def tiled(self, texture: Texture, offset_x: float, offset_y: float, tile_w: float,
              tile_h: float, color=(255, 255, 255), alpha: int = 255,
              blend: Optional[int] = None, area: Optional[tuple] = None) -> None:
        """Cover ``area`` (default: the whole output) with a tileable texture, shifted."""
        if tile_w <= 1 or tile_h <= 1:
            return
        ax, ay, aw, ah = area or (0, 0, self.width, self.height)
        start_x = ax + ((offset_x % tile_w) - tile_w)
        start_y = ay + ((offset_y % tile_h) - tile_h)
        y = start_y
        while y < ay + ah:
            x = start_x
            while x < ax + aw:
                if x + tile_w > ax and y + tile_h > ay:
                    self.image(texture, x, y, tile_w, tile_h, color=color, alpha=alpha,
                               blend=blend)
                x += tile_w
            y += tile_h

    def geometry(self, texture: Optional[Texture], vertices: np.ndarray, count: int,
                 indices: Optional[np.ndarray] = None, index_count: int = 0,
                 blend: int = BLEND) -> None:
        """SDL_RenderGeometry: triangles with per-vertex colour (and texture)."""
        if count <= 0:
            return
        if texture is not None:
            if texture.ptr is None:
                return
            texture.set_blend(blend)       # colour and alpha come from the vertices
        else:
            self.sdl.SDL_SetRenderDrawBlendMode(self.renderer, blend)
        result = self.sdl.SDL_RenderGeometry(
            self.renderer, texture.ptr if texture is not None else None, vertices.ctypes.data,
            int(count), indices.ctypes.data if indices is not None and index_count else None,
            int(index_count))
        if result < 0:
            log.debug("RenderGeometry failed: %s", self.sdl.error())
        self.draw_calls += 1

    # ----------------------------------------------------------- read back
    def read_rgba(self) -> np.ndarray:
        """The current target (or output) as an (H, W, 4) RGBA array. Slow: tests, thumbnails."""
        target = self._target
        w, h = (target.width, target.height) if target else (self.width, self.height)
        buf = np.zeros((h, w, 4), np.uint8)
        self.sdl.check(self.sdl.SDL_RenderReadPixels(self.renderer, None, sdl2.PIXELFORMAT_RGBA32,
                                                     buf.ctypes.data, w * 4), "read pixels")
        return buf

    def read_into(self, address: int, pitch: int, pixel_format: int = sdl2.PIXELFORMAT_ARGB8888) -> None:
        """Copy the finished frame straight into memory (a mapped KMS frame buffer)."""
        self.sdl.check(self.sdl.SDL_RenderReadPixels(self.renderer, None, pixel_format, address,
                                                     pitch), "read pixels")

    def present(self) -> None:
        self.sdl.SDL_RenderPresent(self.renderer)
