"""What every scene is: a lifecycle, a context, and its quality profile.

Lifecycle (driven by ``engine.Engine``):

    create(ctx)      make the scene (a class method; may choose a variant)
    prepare()        CPU work only (NumPy, Pillow): runs on a worker thread
    setup(canvas)    upload textures (render thread)
    update(dt, t)    advance by dt scene-seconds (0 while paused)
    draw(canvas)     draw one frame
    resize(w, h)     the output changed size; return True to be rebuilt
    settings_changed(keys)  return True to be rebuilt
    close()          release every texture the scene made

Scenes draw only through ``gfx.canvas.Canvas`` and never touch SDL, the
window or the input: they do not know which renderer or display is used.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from ..gfx.canvas import BLEND, Canvas, Texture


@dataclass(frozen=True)
class Quality:
    name: str
    fps: int            # frame-rate cap (0 = the display's refresh rate)
    stars: float        # star-count multiplier
    texture: float      # texture-resolution multiplier
    detail: int         # 0 eco .. 3 ultra: layers, octaves, effects


QUALITY = {
    "eco": Quality("eco", 30, 0.4, 0.5, 0),
    "balanced": Quality("balanced", 60, 1.0, 0.75, 1),
    "high": Quality("high", 60, 1.6, 1.0, 2),
    "ultra": Quality("ultra", 0, 2.4, 1.25, 3),
}


def resolve_motion(setting: str, accelerated: bool) -> bool:
    """True for gentle motion: ``auto`` is gentle without a GPU, where frames are few and
    fast movement would jump; slow drifts and fades stay smooth at any frame rate."""
    if setting in ("full", "gentle"):
        return setting == "gentle"
    return not accelerated


def resolve_quality(setting: str, accelerated: bool) -> Quality:
    """``auto`` is Balanced, with or without a GPU (picture quality before frame rate:
    the steady frame rate settles lower instead); never Ultra."""
    if setting in QUALITY:
        return QUALITY[setting]
    return QUALITY["balanced"]


@dataclass
class SceneContext:
    width: int
    height: int
    quality: Quality
    settings: object                      # config.Settings (read only)
    seed: int = 1
    accelerated: bool = True
    wall_clock: Callable[[], float] = time.time
    max_texture: int = 8192
    gentle: bool = False
    # Runs CPU work off the render thread: background(fn, *args) -> Future. None (tests,
    # synchronous engines): do the work where it is needed.
    background: Optional[Callable] = None
    # True once the scene is no longer wanted (the app is closing): long preparations
    # stop at their next checkpoint instead of keeping the process alive.
    cancelled: Callable[[], bool] = lambda: False
    extras: dict = field(default_factory=dict)

    @property
    def unit(self) -> float:
        """Resolution-independent size unit: 1.0 at 1080 pixels on the short side."""
        return min(self.width, self.height) / 1080.0

    def rng(self, salt: str = "") -> np.random.Generator:
        digest = hashlib.sha256(f"{self.seed}:{salt}".encode()).digest()
        return np.random.default_rng(int.from_bytes(digest[:8], "little"))

    def texture_size(self, base: int, minimum: int = 64) -> int:
        """A texture edge for ``base`` pixels at 1080p, scaled by quality and output size."""
        scale = self.quality.texture * max(self.width, self.height) / 1920.0
        return int(max(minimum, min(self.max_texture, round(base * scale))))

    def setting(self, key: str, default=None):
        getter = getattr(self.settings, "get", None)
        return getter(key, default) if getter else default


class Cancelled(Exception):
    """A scene's preparation stopped because the scene is no longer wanted."""


class Scene:
    """Base class; see the module docstring for the lifecycle."""

    id = "scene"
    max_fps: Optional[int] = None         # a calm scene may ask for fewer frames

    def __init__(self, ctx: SceneContext):
        self.ctx = ctx
        self.width = ctx.width
        self.height = ctx.height
        self.textures: list = []
        self.t = 0.0

    # -- lifecycle -----------------------------------------------------
    @classmethod
    def create(cls, ctx: SceneContext) -> "Scene":
        """The scene object for ``ctx``; a scene with variants picks one from its settings."""
        return cls(ctx)

    def prepare(self) -> None:
        """CPU-only work (worker thread): build arrays, never call the canvas."""

    def setup(self, canvas: Canvas) -> None:
        """Upload what ``prepare`` built."""

    def resize(self, width: int, height: int) -> bool:
        self.width, self.height = width, height
        return False

    def update(self, dt: float, t: float) -> None:
        self.t = t

    def draw(self, canvas: Canvas) -> None:
        canvas.clear((0, 0, 0))

    def settings_changed(self, keys: set) -> bool:
        return False

    def close(self) -> None:
        for texture in self.textures:
            texture.destroy()
        self.textures.clear()

    # -- helpers -------------------------------------------------------
    def upload(self, canvas: Canvas, rgba: np.ndarray, blend: int = BLEND, name: str = "",
               linear: bool = True) -> Texture:
        texture = canvas.texture(rgba, blend=blend, linear=linear, name=f"{self.id}.{name}")
        self.textures.append(texture)
        return texture

    def setting(self, key: str, default=None):
        return self.ctx.setting(key, default)

    def checkpoint(self) -> None:
        """Call between expensive steps of ``prepare``: stops it when no longer wanted."""
        if self.ctx.cancelled():
            raise Cancelled(self.id)

    @property
    def unit(self) -> float:
        return min(self.width, self.height) / 1080.0

    @property
    def software(self) -> bool:
        """Drawn by SDL's software renderer: scaling and turning images are costly."""
        return not self.ctx.accelerated

    @property
    def gentle(self) -> bool:
        return self.ctx.gentle

    def fit(self, rgba, width: int, height: int):
        """On the software renderer, scale a texture once to the size it is drawn at, so
        each frame copies it 1:1 (scaling while blending costs a lot without a GPU)."""
        if not self.software:
            return rgba
        width, height = max(1, int(round(width))), max(1, int(round(height)))
        if rgba.shape[1] == width and rgba.shape[0] == height:
            return rgba
        from PIL import Image
        resample = getattr(Image, "Resampling", Image).BILINEAR
        return np.asarray(Image.fromarray(rgba, "RGBA").resize((width, height), resample),
                          np.uint8).copy()
