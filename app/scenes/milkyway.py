"""Scene A, inside view: the Milky Way seen from within the disk.

Like a dark-sky photograph: a bright band of unresolved stars and star
clouds crosses the sky, denser and warmer towards the galactic core; a broken
dark rift runs along the band and dust clouds break it up; a few faint pink
star-forming regions glow in it. Stars stand in front at three depths and
drift with the band at slightly different rates (parallax).

The band is one baked panorama, PANORAMA_SCREENS screen widths around and
seamless across its width, drifting slowly sideways: the sky turning, never a
disk spinning. On SDL's software renderer the panorama is drawn at the two
whole pixels either side of its true position and blended, so a drift of
under a pixel a second stays smooth without a GPU.

Illustrative, not a map of the real sky.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise
from ..gfx.canvas import BLEND, NONE
from .base import Scene
from .parts import StarField, common_sprites, density_count

PANORAMA_SCREENS = 2.6        # the panorama is this many screen widths around
SCREEN_SECONDS = 600.0        # Full motion: seconds for the band to drift one screen width
GENTLE_DRIFT = 0.5            # Gentle motion: the drift at this fraction
PARALLAX = (1.0, 1.12, 1.28)  # band stars, middle and near stars: drift times this
CORE_AT = 0.32                # where the galactic core sits along the panorama (0..1)
BAND_LEVEL = 0.62             # brightness of the band's light (the core peaks near 1)
SKY_TOP, SKY_BOTTOM = (2, 3, 9), (6, 7, 15)
BAND_COLOR = (0.78, 0.83, 0.96)   # cool white
CORE_COLOR = (1.0, 0.8, 0.58)     # warm: old stars towards the centre
HEART_COLOR = (1.0, 0.93, 0.8)    # the nucleus, nearly white
KNOT_COLOR = (0.62, 0.2, 0.34)    # star-forming regions


def _smooth(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _field(rng, width: int, height: int, cells_x: int, cells_y: int, octaves: int,
           ridged: bool = False, warp: float = 0.0, shrink: int = 1) -> np.ndarray:
    """fBm in about 0..1 with ``cells_x`` by ``cells_y`` lattice cells: whole periods, so
    it tiles; more cells down than the shape needs stretches features along the band.
    Made at 1/``shrink`` of the size and scaled up (smooth fields lose nothing)."""
    small_w, small_h = max(8, width // shrink), max(8, height // shrink)
    if (small_w, small_h) != (width, height):
        small = _field(rng, small_w, small_h, cells_x, cells_y, octaves, ridged, warp)
        return noise.upsample(small, width, height)
    u, v = noise.grid(width, height, cells_x, cells_y)
    if warp:
        q = noise.FBM(rng, cells_x, cells_y, max(2, octaves - 2)).at(u, v)
        r = noise.FBM(rng, cells_x, cells_y, max(2, octaves - 2)).at(u + 5.2, v + 1.3)
        u, v = u + np.float32(warp) * q, v + np.float32(warp) * r
    n = noise.FBM(rng, cells_x, cells_y, octaves).at(u, v, ridged)
    return n if ridged else n * np.float32(0.5) + np.float32(0.5)


def panorama(rng: np.random.Generator, width: int, height: int, detail: int,
             check=lambda: None) -> tuple:
    """(opaque RGBA image, band light) of the sky around, seamless across ``width``.
    ``check()`` is called between the expensive steps (it raises to stop early)."""
    f32 = np.float32
    x = (np.arange(width, dtype=f32) + 0.5) / f32(width)
    y = ((np.arange(height, dtype=f32) + 0.5) / f32(height))[:, None]
    phi = f32(2 * math.pi) * x
    p0, p1, p2 = rng.uniform(0, 2 * math.pi, 3)
    centre = 0.5 + 0.17 * np.sin(phi + f32(p0)) + 0.04 * np.sin(2 * phi + f32(p1))
    along = ((x - f32(CORE_AT) + 0.5) % 1.0) - 0.5                  # signed, wraps
    core = np.exp(-(along / f32(0.065)) ** 2)                        # (W,)
    nucleus = np.exp(-(along / f32(0.022)) ** 2)
    half = 0.08 + 0.07 * core                                        # band half-width
    d = (y - centre[None, :]) / half[None, :]
    profile = np.exp(-0.5 * d * d)
    wide = np.exp(-0.5 * (d / 2.4) ** 2)
    octaves = 4 + min(2, detail)
    # Features are stretched along the band (more cells across the width than square).
    clumps = noise.contrast(_field(rng, width, height, 14, 7, octaves, warp=1.2, shrink=4),
                            0.3, 0.85)
    check()
    fine = _field(rng, width, height, 44, 20, 3, shrink=2)
    check()
    light = profile * (0.42 + 0.78 * clumps) * (0.8 + 0.4 * fine) + 0.26 * wide * (0.7 + 0.3 * fine)
    bulge = core[None, :] * np.exp(-0.5 * (d / 1.05) ** 2) * (0.7 + 0.3 * clumps)
    light = light + 0.75 * bulge + 0.6 * nucleus[None, :] * np.exp(-0.5 * (d / 0.55) ** 2)
    # Dust: a long broken rift along the band, dark clouds near it, faint threads.
    rift_centre = centre + half * 0.22 * np.sin(3 * phi + f32(p2))
    rift = np.exp(-0.5 * ((y - rift_centre[None, :]) / (half[None, :] * 0.26)) ** 2)
    broken = noise.contrast(_field(rng, width, height, 18, 4, 4, shrink=4), 0.34, 0.62)
    clouds = noise.contrast(_field(rng, width, height, 12, 5, octaves, warp=1.0, shrink=4),
                            0.58, 0.78)
    check()
    threads = noise.contrast(_field(rng, width, height, 30, 9, 3, ridged=True, shrink=2),
                             0.8, 0.97)
    check()
    near_band = np.exp(-0.5 * (d / 1.5) ** 2)
    dust = np.clip(0.8 * rift * broken + 0.7 * clouds * near_band + 0.18 * threads * profile,
                   0.0, 0.92)
    light = light * (1.0 - dust)
    warmth = _smooth(core[None, :] * np.exp(-0.5 * (d / 1.5) ** 2) * 1.25)
    heart = _smooth(nucleus[None, :] * np.exp(-0.5 * (d / 0.8) ** 2) * 1.2)
    color = (np.asarray(BAND_COLOR, f32) * (1.0 - warmth[..., None])
             + np.asarray(CORE_COLOR, f32) * warmth[..., None])
    color = color * (1.0 - heart[..., None]) + np.asarray(HEART_COLOR, f32) * heart[..., None]
    rgb = light[..., None] * color
    # Dust reddens what it lets through: blue is dimmed more than red.
    rgb *= 1.0 - dust[..., None] * np.asarray((0.0, 0.12, 0.3), f32)
    knots = noise.contrast(_field(rng, width, height, 64, 14, 2, shrink=2), 0.8, 0.93) \
        * profile * (1 - dust)
    check()
    rgb += knots[..., None] * np.asarray(KNOT_COLOR, f32) * 0.45
    # Unresolved stars: fine points, crowded where the band is bright.
    chance = np.clip(light, 0, 1.3) * f32(0.07) + f32(0.004)
    points = (rng.random((height, width), dtype=f32) < chance) * rng.random((height, width),
                                                                             dtype=f32) ** 3
    rgb = rgb * f32(BAND_LEVEL) + points[..., None] * f32(0.55)
    sky = (np.asarray(SKY_TOP, f32) + (np.asarray(SKY_BOTTOM, f32) - np.asarray(SKY_TOP, f32))
           * y[..., None]) / 255.0
    out = (sky + rgb) * 255.0 + rng.random((height, width, 1), dtype=f32) - 0.5   # dither
    image = np.empty((height, width, 4), np.uint8)
    image[..., :3] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    image[..., 3] = 255
    return image, np.clip(light, 0.0, None)


class InsideGalaxy(Scene):
    id = "galaxy"
    STARS = 900            # foreground stars at 1080p (two depths)
    BAND_STARS = 700       # resolved stars in the band, drifting with it
    BRIGHT = 14

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        scale = 1.0 if self.software else min(1.0, q.texture + 0.25)   # software: drawn 1:1
        ph = max(64, int(round(h * scale)))
        pw = max(128, int(round(w * PANORAMA_SCREENS * scale)))
        self.panorama_px, light = panorama(ctx.rng("panorama"), pw, ph, q.detail, self.checkpoint)
        # Resolved stars crowd into the band: positions in the panorama (0..1).
        brng = ctx.rng("band-stars")
        weights = light.astype(np.float64).ravel() ** 1.6 + 1e-9
        n = max(16, int(self.BAND_STARS * q.stars))
        picks = brng.choice(weights.size, n, p=weights / weights.sum())
        self.band_x = ((picks % pw + brng.random(n)) / pw).astype(np.float32)
        self.band_y = ((picks // pw + brng.random(n)) / ph).astype(np.float32)
        self.band_stars = StarField(brng, 0, size=(1.2, 3.8), twinkle=0.3, saturation=0.45,
                                    faintness=2.2, positions=(self.band_x, self.band_y))
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.middle = StarField(ctx.rng("middle"), capacity, size=(1.4, 5.0), twinkle=0.3,
                                twinkle_speed=(0.08, 0.8), saturation=0.5)
        self.near = StarField(ctx.rng("near"), self.BRIGHT, region=(0, 0.03, 1, 0.97),
                              size=(11.0, 26.0), twinkle=0.25, twinkle_speed=(0.1, 0.6),
                              saturation=0.45, faintness=1.2)
        if self.gentle:
            for field in (self.band_stars, self.middle, self.near):
                field.calm()
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.panorama = self.upload(canvas, self.panorama_px, NONE, "panorama")
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.spike_tex = self.upload(canvas, self.sprites["spike"], name="spike")
        self.panorama_px = self.sprites = None

    def resize(self, width: int, height: int) -> bool:
        super().resize(width, height)
        return True                   # the panorama is made for one size

    def settings_changed(self, keys: set) -> bool:
        return "galaxy_view" in keys

    def drift(self, t: float) -> float:
        """How far the band has drifted, in pixels of the output (grows without bound)."""
        rate = self.width / SCREEN_SECONDS * (GENTLE_DRIFT if self.gentle else 1.0)
        return t * rate

    def draw(self, canvas) -> None:
        w, h, t = self.width, self.height, self.t
        offset = self.drift(t)
        texture = self.panorama
        if self.software:
            # Two whole-pixel copies blended: a sub-pixel shift without a GPU.
            whole = math.floor(offset)
            part = offset - whole
            tw, th = texture.width, texture.height
            canvas.tiled(texture, -whole, 0, tw, th, blend=NONE)
            if part > 1.0 / 255:
                canvas.tiled(texture, -whole - 1, 0, tw, th, alpha=int(round(255 * part)),
                             blend=BLEND)
            span = tw
        else:
            span = w * PANORAMA_SCREENS
            canvas.tiled(texture, -offset, 0, span, h, blend=NONE)
        density = float(self.setting("star_density", 1.0))
        # Band stars ride with the panorama; those not on screen are parked outside it.
        bx = (self.band_x * np.float32(span) - np.float32(offset * PARALLAX[0])) % np.float32(span)
        bx = np.where(bx < w + 8, bx, -64.0).astype(np.float32)
        by = self.band_y * np.float32(h)
        count = max(4, int(len(bx) * min(1.0, density)))
        self.band_stars.draw(canvas, self.star_tex, t, w, h, count=count, positions=(bx, by),
                             alpha=0.9)
        _, middle = density_count(self.STARS, self.ctx.quality, density)
        self.middle.draw(canvas, self.star_tex, t, w, h, count=middle,
                         offset_x=-offset * PARALLAX[1], wrap=True, alpha=0.85)
        self.near.draw(canvas, self.spike_tex, t, w, h, offset_x=-offset * PARALLAX[2], wrap=True,
                       alpha=0.8)
