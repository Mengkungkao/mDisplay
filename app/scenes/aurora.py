"""Scene D — Aurora: a great display over a lake, as in a long-exposure photograph.

The curtains sweep across the sky with fine rays that all point at one spot
above the picture (the magnetic zenith, so they fan out in perspective). Each
curtain's lower border glows bright green, yellow-green where it is
strongest; higher up the rays turn pink and magenta (red oxygen light mixed
with blue), lavender-white where pink and green overlap, then violet; where
a curtain is less red its upper part is teal. Thin violet streaks reach the
top of the sky, stars shine through, a dark treeline of islands closes the
horizon and the lake reflects the light (the mountains setting).

The light is added up physically (emission adds), then softened with a glow
and tone-mapped like a photograph, so overlaps go towards white instead of
clipping. Each picture is a full-detail NumPy render made on the worker
thread; the render thread only blends two consecutive pictures, so the
motion is smooth on a small board even when one picture takes half a second.
"""

from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

from ..gfx import noise
from ..gfx.canvas import BLEND, NONE
from .base import Scene
from .parts import StarField, add_trees, common_sprites, density_count, ridge_line

# Where the rays point: above the picture, right of centre (fractions of the screen).
ZENITH = (0.62, -0.55)
HORIZON = 0.8                   # the lake's far shore, a share of the screen's height
NO_HORIZON = 1.06               # with the mountains setting off: sky only
# Each curtain: lower border from one point to another (x, y as screen fractions), its bow
# (fraction of the radius), reach towards the zenith at its two ends, strength, redness
# at its two ends (how pink its upper part is), striation (how strongly rays show),
# number of rays across it (fine streaks) and how fast it moves.
CURTAINS = (
    ((-0.02, 0.84), (1.05, 0.58), 0.05, (0.5, 0.72), 1.6, (0.95, 0.1), 0.2, 70, 1.0),
    ((0.08, 0.64), (0.9, 0.4), -0.02, (0.4, 0.6), 0.45, (1.0, 0.5), 0.25, 60, 0.8),
    ((0.02, 0.6), (0.38, 0.3), 0.0, (0.8, 0.95), 0.3, (0.25, 0.3), 0.95, 22, 0.6),
)
STREAK_CURTAIN = 2              # the third is the thin violet streaks: few, sharp rays
# Emission colours in linear light (r, g, b).
GREEN = (0.24, 1.0, 0.14)       # oxygen 557.7 nm; yellow-green once it saturates
PINK = (1.0, 0.03, 0.32)        # oxygen 630 nm red with nitrogen's blue
VIOLET = (0.32, 0.1, 1.0)
TEAL = (0.0, 0.6, 0.72)
SKY_TOP, SKY_HORIZON = (5, 4, 18), (9, 24, 40)    # display colours
EXPOSURE = 1.6
BLOOM = 0.3                     # the soft glow around bright light
LAKE_REFLECTION = 0.24
MOTION_GENTLE = 0.4             # gentle motion: the aurora changes at 40%
KEY_STEP = 0.9                  # seconds of aurora time between pictures (at least)
BINS = 1024                     # brightness samples across each curtain
PROFILE = 512                   # samples of the colour profiles up a ray


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _linear(rgb) -> np.ndarray:
    return (np.asarray(rgb, np.float32) / 255.0) ** 2.2


def profiles() -> tuple:
    """(s values, green, pink, violet, teal) up a ray: s = 0 at the lower border, 1 at the
    top of the curtain, negative below it. Green is low and brightest at the border,
    pink higher, violet highest: they overlap only a little, so each stays saturated
    and only the brightest overlaps go towards white."""
    s = np.linspace(-0.3, 1.3, PROFILE).astype(np.float32)
    rise = _smooth(s, -0.015, 0.02)
    below = np.exp(np.minimum(s, 0.0) * 40.0) * (s < 0) * 0.3          # faint glow under it
    up = np.maximum(s, 0)
    green = rise * (1.0 * np.exp(-up / 0.3) + 1.2 * np.exp(-up / 0.05)) + below
    top = 1.0 - _smooth(s, 0.8, 1.12)
    pink = _smooth(s, 0.2, 0.45) * np.exp(-((s - 0.55) ** 2) / 0.09) * top
    violet = _smooth(s, 0.5, 0.9) * top * 0.45
    teal = _smooth(s, 0.05, 0.28) * np.exp(-((s - 0.36) ** 2) / 0.07) * top
    return s, green.astype(np.float32), pink.astype(np.float32), violet.astype(np.float32), \
        teal.astype(np.float32)


def _blur(image: np.ndarray, radius: int, passes: int = 3) -> np.ndarray:
    """Box blur repeated (close to a Gaussian), edges clamped; (h, w, c) float."""
    out = image
    for axis in (0, 1):
        for _ in range(passes):
            pad = [(0, 0)] * out.ndim
            pad[axis] = (radius + 1, radius)
            p = np.pad(out, pad, mode="edge")
            c = np.cumsum(p, axis=axis, dtype=np.float32)
            n = out.shape[axis]
            hi = np.take(c, np.arange(2 * radius + 1, 2 * radius + 1 + n), axis=axis)
            lo = np.take(c, np.arange(0, n), axis=axis)
            out = (hi - lo) / np.float32(2 * radius + 1)
    return out


def treeline(rng, width: int, height: float) -> np.ndarray:
    """Heights (pixels above the shore) of low wooded islands, a distant hill and the
    forest on the right: flat dark shapes with fine treetops, as seen across a lake."""
    x = (np.arange(width, dtype=np.float32) + 0.5) / width
    islands = noise.FBM(rng, 6, 1, 3).at(x * 6.0, np.zeros_like(x)) * 0.5 + 0.5
    land = _smooth(islands, 0.4, 0.46)                 # open water between the islands
    land = np.maximum(land, _smooth(x, 0.86, 0.9))     # the forest on the right
    ground = height * 0.15 * land
    tops = ground + height * 0.32 * land * (0.6 + 0.4 * noise.FBM(rng, 160, 1, 2).at(
        x * 160.0, np.zeros_like(x)))
    trees = add_trees(rng, tops, count=int(width / 3), height=height * 0.25,
                      width_px=max(1.5, height * 0.12), clustered=True) * land
    hill = height * 0.75 * np.exp(-((x - 0.68) / 0.05) ** 2)
    forest = height * 1.5 * _smooth(x, 0.86, 0.95) * (0.85 + 0.15 * noise.FBM(rng, 90, 1, 2).at(
        x * 90.0, np.zeros_like(x)))
    return np.maximum(trees, np.maximum(hill, forest)).astype(np.float32)


class AuroraSky:
    """The picture at one size; ``render(t)`` is a pure function of the aurora's time
    (reads only what the constructor made), so it can run on the worker thread."""

    def __init__(self, rng: np.random.Generator, width: int, height: int, lake: bool,
                 detail: int):
        self.width, self.height = w, h = int(width), int(height)
        self.horizon = int(round(h * (HORIZON if lake else NO_HORIZON)))
        f32 = np.float32
        y, x = np.mgrid[0:h, 0:w].astype(f32)
        zx, zy = ZENITH[0] * w, ZENITH[1] * h
        phi = np.arctan2(y + 0.5 - zy, x + 0.5 - zx)
        self.rho = (np.hypot(x + 0.5 - zx, y + 0.5 - zy) / h).astype(f32)
        self.curtains = []
        for index, (a, b, bow, reach, strength, redness, striation, rays, speed) in \
                enumerate(CURTAINS):
            pa = math.atan2(a[1] * h - zy, a[0] * w - zx)
            pb = math.atan2(b[1] * h - zy, b[0] * w - zx)
            ra = math.hypot(a[0] * w - zx, a[1] * h - zy) / h
            rb = math.hypot(b[0] * w - zx, b[1] * h - zy) / h
            u = ((phi - pa) / (pb - pa)).astype(f32)
            index_map = np.clip((u * BINS).astype(np.int32), -1, BINS)
            inside = (index_map >= 0) & (index_map < BINS)
            index_map = np.where(inside, index_map, BINS)       # BINS: an always-dark bin
            sky = y < self.horizon
            self.curtains.append({
                "bins": np.where(sky, index_map, BINS).astype(np.int32),
                "ra": ra, "rb": rb, "bow": bow, "reach": reach, "strength": strength,
                "lengths": noise.Noise1D(rng, cells=rays, octaves=2, time_cells=256),
                "redness": redness, "striation": striation, "speed": speed,
                "streaks": index == STREAK_CURTAIN,
                "shape": noise.Noise1D(rng, cells=6, octaves=3, time_cells=64),
                "folds": noise.Noise1D(rng, cells=9, octaves=3, time_cells=64),
                "rays": noise.Noise1D(rng, cells=rays, octaves=2, time_cells=256),
                "phase": rng.uniform(0, 100),
            })
        self.u = ((np.arange(BINS) + 0.5) / BINS).astype(f32)
        self.s_axis, *self.luts = profiles()
        self.s_scale = (PROFILE - 1) / (self.s_axis[-1] - self.s_axis[0])
        self.colors = [np.asarray(c, f32) for c in (GREEN, PINK, VIOLET, TEAL)]
        self.activity = noise.Noise1D(rng, cells=4, octaves=2, time_cells=32)
        # The sky behind (linear light): dark violet-blue above, teal-blue near the shore.
        t = np.clip(y / max(1, self.horizon), 0, 1)[..., None] ** 1.6
        side = (x / w)[..., None]
        top = _linear(SKY_TOP) * (1.0 + 0.6 * (1 - side))      # a little more violet on the left
        self.sky = (top * (1 - t) + _linear(SKY_HORIZON) * t).astype(f32)
        # Islands and forest on the shore; the lake below, faintly lit.
        self.trees = None
        if lake:
            heights = treeline(rng, w, h * 0.05)
            above = (self.horizon - y)
            self.trees = (above > 0) & (above <= heights[None, :])
        self.ripples = (0.85 + 0.15 * noise.fbm_image(rng, w, max(8, h - self.horizon),
                                                      cells_across=24, octaves=2)
                        ) if lake and self.horizon < h else None
        levels = np.linspace(0.0, 1.0, 4096, dtype=np.float32) ** (1 / 2.2)
        self.gamma = np.clip(levels * 255.0 + 0.5, 0, 255).astype(np.uint8)
        self.detail = detail

    def level(self, t: float) -> float:
        """Overall activity 0.55..1.0, changing over minutes."""
        a = float(self.activity.at(np.array([0.3], np.float32), t * 0.004)[0])
        return 0.55 + 0.45 * min(1.0, max(0.0, a * 1.2 + 0.55))

    def _along(self, c: dict, t: float, activity: float) -> tuple:
        """(brightness, lower-border radius, reach, redness) at the BINS positions."""
        u, s = self.u, t * c["speed"] + c["phase"]
        bow = c["bow"] * np.sin(np.pi * u)
        wave = 0.03 * np.sin(2 * np.pi * (1.3 * u + 0.011 * s)) \
            + 0.02 * np.sin(2 * np.pi * (2.9 * u - 0.017 * s) + 1.7) \
            + 0.035 * c["shape"].at(u, s * 0.01)
        radius = (c["ra"] + (c["rb"] - c["ra"]) * u) * (1.0 + bow + wave)
        r0, r1 = c["reach"]
        reach = (r0 + (r1 - r0) * u) * (1.0 + 0.12 * c["shape"].at(u + 0.37, s * 0.008))
        # Each ray ends at its own height, as real rays do.
        reach = reach * (0.85 + 0.15 * np.clip(c["lengths"].at(u, s * 0.02) * 1.5 + 0.5, 0, 1))
        folds = np.clip(c["folds"].at(u, s * 0.012) * 0.95 + 0.62, 0, 1.2) ** 1.5
        rays = np.clip(c["rays"].at(u - s * 0.0009, s * 0.025) * 1.4 + 0.5, 0, 1)
        if c["streaks"]:
            rays = rays ** 6.0                              # a few sharp, separate streaks
        light = folds * (1.0 - c["striation"] + c["striation"] * rays)
        ends = _smooth(u, 0.0, 0.12) * (1.0 - _smooth(u, 0.85, 1.0))
        light = light * ends * c["strength"] * activity
        r0, r1 = c["redness"]
        redness = np.clip(r0 + (r1 - r0) * u + 0.25 * c["folds"].at(u + 0.61, s * 0.006), 0, 1)
        # One dark bin past the end, for pixels outside the curtain.
        pad = np.zeros(1, np.float32)
        return (np.concatenate([light, pad]).astype(np.float32),
                np.concatenate([radius, np.ones(1)]).astype(np.float32),
                np.concatenate([reach, np.ones(1)]).astype(np.float32),
                np.concatenate([redness, pad]).astype(np.float32))

    def render(self, t: float) -> np.ndarray:
        """The picture at aurora time ``t`` as an opaque (h, w, 4) uint8 image."""
        h, w = self.height, self.width
        activity = self.level(t)
        green = np.zeros((h, w), np.float32)
        pink = np.zeros((h, w), np.float32)
        violet = np.zeros((h, w), np.float32)
        teal = np.zeros((h, w), np.float32)
        g_lut, p_lut, v_lut, t_lut = self.luts
        for c in self.curtains:
            light, radius, reach, redness = self._along(c, t, activity)
            b = c["bins"]
            r = radius[b]
            s = (r - self.rho) / (r * reach[b])
            k = np.clip((s - self.s_axis[0]) * self.s_scale, 0, PROFILE - 1).astype(np.int32)
            a = light[b]
            red = redness[b]
            if c["streaks"]:
                violet += a * (v_lut[k] + 0.6 * p_lut[k] + 0.35 * g_lut[k])
                continue
            green += a * g_lut[k]
            pink += a * red * p_lut[k]
            teal += a * (1.0 - red) * t_lut[k]
            violet += a * (0.15 + 0.35 * red) * v_lut[k]
        rgb = self.sky.copy()
        for plane, color in zip((green, pink, violet, teal), self.colors):
            rgb += plane[..., None] * color
        # Glow: the bright light spread wide, as in a photograph.
        small = rgb[::4, ::4]
        glow = _blur(small, max(2, h // 40))
        rgb += BLOOM * np.repeat(np.repeat(glow, 4, axis=0), 4, axis=1)[:h, :w]
        if self.trees is not None:
            rgb[self.trees] = _linear((2, 3, 5))
        if self.horizon < h:
            self._lake(rgb)
        mapped = 1.0 - np.exp(-rgb * np.float32(EXPOSURE))
        image = np.empty((h, w, 4), np.uint8)
        image[..., :3] = self.gamma[(mapped * 4095.0).astype(np.int32)]
        image[..., 3] = 255
        return image

    def _lake(self, rgb: np.ndarray) -> None:
        """The lake: the sky and shore mirrored, dimmed with distance, softened, rippled."""
        h, w = self.height, self.width
        y0 = self.horizon
        rows = np.arange(y0, h)
        source = np.clip(2 * y0 - rows - 1, 0, y0 - 1)
        mirror = rgb[source]
        mirror = (mirror + np.roll(mirror, 2, axis=1) + np.roll(mirror, -2, axis=1)) / 3.0
        mirror = 0.5 * mirror + 0.25 * (np.roll(mirror, 3, axis=0) + np.roll(mirror, -3, axis=0))
        fade = np.exp(-(rows - y0) / (0.22 * h)).astype(np.float32)[:, None, None]
        water = _linear((3, 7, 9))
        rgb[y0:] = water + LAKE_REFLECTION * mirror * fade * self.ripples[..., None]


class AuroraScene(Scene):
    id = "aurora"
    STARS = 1100
    KEYFRAME_MAX_WIDTH = 1280      # GPU: pictures made at most this wide, then scaled

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        scale = 1.0 if self.software else min(1.0, self.KEYFRAME_MAX_WIDTH / max(1, w))
        kw, kh = max(64, int(round(w * scale))), max(36, int(round(h * scale)))
        lake = bool(self.setting("mountains", True))
        self.picture = AuroraSky(ctx.rng("aurora"), kw, kh, lake, q.detail)
        self.checkpoint()
        self.rate = MOTION_GENTLE if self.gentle else 1.0
        self.step = KEY_STEP
        self.tau = 0.0
        started = time.perf_counter()
        first = self.picture.render(0.0)
        self.render_seconds = time.perf_counter() - started
        self.checkpoint()
        self.ready = deque([(0.0, first), (self.step, self.picture.render(self.step))])
        horizon = HORIZON if lake else 1.0
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, region=(0, 0, 1, horizon - 0.06),
                               size=(1.2, 4.6), twinkle=0.3, twinkle_speed=(0.08, 0.8),
                               saturation=0.45)
        if self.gentle:
            self.stars.calm()
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        # Pictures: [(aurora time, texture)]; a free texture is reused for the next one.
        self.frames = deque()
        for when, pixels in self.ready:
            self.frames.append((when, self.upload(canvas, pixels, NONE, f"aurora{len(self.frames)}")))
        self.ready.clear()
        self.spare = []
        self.pending = None
        self.sprites = None

    def settings_changed(self, keys: set) -> bool:
        return "mountains" in keys

    def resize(self, width: int, height: int) -> bool:
        super().resize(width, height)
        return True                    # the pictures are made for one size

    def close(self) -> None:
        if getattr(self, "pending", None) is not None:
            self.pending[1].cancel()
        super().close()

    def update(self, dt: float, t: float) -> None:
        self.t = t
        self.tau += dt * self.rate

    # -- pictures ---------------------------------------------------------
    def _render_timed(self, when: float):
        started = time.perf_counter()
        pixels = self.picture.render(when)
        return pixels, time.perf_counter() - started

    def _next_time(self) -> float:
        """The next picture's aurora time: KEY_STEP ahead, or further when one picture
        takes longer than that to make (the blend then spans more time; it never waits)."""
        real = self.render_seconds * 1.4
        return self.frames[-1][0] + max(self.step, real * self.rate)

    def _add(self, canvas, when: float, pixels) -> None:
        if self.spare:
            texture = self.spare.pop()
            canvas.update(texture, pixels)
        else:
            texture = self.upload(canvas, pixels, NONE, f"aurora{len(self.textures)}")
        self.frames.append((when, texture))

    def _keep_up(self, canvas) -> None:
        if self.pending is not None and self.pending[1].done():
            when, future = self.pending
            self.pending = None
            if not future.cancelled() and future.exception() is None:
                pixels, seconds = future.result()
                self.render_seconds = 0.7 * self.render_seconds + 0.3 * seconds
                self._add(canvas, when, pixels)
        background = self.ctx.background
        if background is None:
            # No worker (tests): make each picture when it is needed.
            while self.frames[-1][0] <= self.tau:
                when = self._next_time()
                self._add(canvas, when, self.picture.render(when))
        elif self.pending is None and len(self.frames) < 3:
            when = self._next_time()
            self.pending = (when, background(self._render_timed, when))
        # The aurora never runs ahead of the pictures made: it waits rather than jumps.
        self.tau = min(self.tau, self.frames[-1][0])
        while len(self.frames) > 2 and self.frames[1][0] <= self.tau:
            self.spare.append(self.frames.popleft()[1])

    def draw(self, canvas) -> None:
        w, h, t = self.width, self.height, self.t
        self._keep_up(canvas)
        (t0, a), (t1, b) = self.frames[0], self.frames[1]
        f = min(1.0, max(0.0, (self.tau - t0) / max(1e-6, t1 - t0)))
        canvas.image(a, 0, 0, w, h, blend=NONE)
        if f > 1.0 / 255:
            canvas.image(b, 0, 0, w, h, alpha=int(round(255 * f)), blend=BLEND)
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, alpha=0.75)
