"""Scene D — Aurora, seen from below: curtains overhead rising towards the zenith.

Looking up into an aurora, its rays follow the magnetic field lines, which in
perspective all point at one spot near the zenith: the corona. Each curtain
here is a ring of rays whose lower ends lie on a wavy arc around that spot
and whose tops reach towards it, bright green at the bottom, through cyan, to
a faint violet. The arc, the rays' widths, brightness and slow drift come
from several waves and evolving noise, so the motion never repeats
mechanically; stars show through the gaps between the rays. A thin horizon
closes the bottom edge (the mountains setting). The overall activity rises
and falls over minutes.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise
from ..gfx.batch import Mesh
from ..gfx.canvas import ADD, BLEND, NONE
from .base import Scene
from .parts import (Grain, StarField, add_trees, common_sprites, density_count, ridge_line,
                    silhouette, sky_gradient)

# Colour up a ray, from its lower end towards the zenith: (fraction, (r, g, b), alpha)
CURTAIN = ((0.0, (90, 255, 170), 0.0), (0.04, (110, 255, 175), 1.0), (0.14, (70, 255, 160), 0.85),
           (0.42, (50, 230, 180), 0.6), (0.72, (50, 160, 215), 0.38), (1.0, (130, 80, 210), 0.0))
# Software renderer: SDL draws long diagonal triangles slowly (it pays per triangle and
# for each one's whole bounding box), so there the curtains are computed with NumPy into
# a small image each frame instead: around the zenith every ray is a line of constant
# angle, so the picture is a brightness along the arc times a profile up the rays.
SOFTWARE_SCALE = 0.5            # the image's size, a share of the screen's
SOFTWARE_BINS = 512             # brightness samples along each arc
SKY = [(0.0, (3, 7, 14)), (0.5, (2, 5, 12)), (1.0, (2, 4, 9))]
ZENITH = (0.5, 0.12)            # where the rays converge, as fractions of the screen
ARC = (-0.14 * math.pi, 1.14 * math.pi)   # the arcs' angular span (0 = right, pi/2 = down)
# (arc radii: x screen width, y screen height; reach towards the zenith (min, max);
#  rays at detail 0..3; folds; strength; speed; tint)
CURTAINS = (((0.56, 0.74), (0.55, 0.92), (44, 96, 136, 176), 7, 1.0, 1.0, (1.0, 1.0, 1.0)),
            ((0.4, 0.5), (0.4, 0.8), (28, 60, 84, 110), 5, 0.6, 0.7, (1.0, 0.8, 1.12)))
RAY_FILL = (0.9, 2.4)           # a ray's width in ray spacings (rays overlap into a sheet)
RAY_REFERENCE = 50              # the spacing RAY_FILL counts in: more rays (higher quality)
                                # overlap more and share the light, instead of getting thinner
GLOW_COLOR = (40, 200, 120)
GLOW_PEAK = 30                  # alpha of the corona glow at full activity
GLOW_MEAN = 20                  # baked in at about the average activity (software renderer)
CURTAIN_GENTLE = 0.4            # curtains move at 40% in gentle motion
HORIZON = 0.075                 # the horizon's height, a share of the screen


def bake_glow(sky: np.ndarray, color, level: float) -> np.ndarray:
    """The corona glow ``draw`` adds on a GPU (round, centred on the zenith, 0.9 of the
    screen's height across) added into the sky image once."""
    h, w = sky.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot(x + 0.5 - ZENITH[0] * w, y + 0.5 - ZENITH[1] * h) / (0.45 * h)
    alpha = (1.0 - np.clip(r, 0, 1)) ** 1.6 * level
    out = sky.astype(np.float32)
    out[..., :3] += alpha[..., None] * np.asarray(color, np.float32)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _ray_indices(rays: int, rows: int) -> np.ndarray:
    """Each ray is three columns of vertices (left edge, middle, right edge), two cells
    wide, two triangles per cell; ray i, row j, column k is vertex
    i * (rows + 1) * 3 + j * 3 + k. Untextured: the soft edges come from the vertex
    alpha (0 at the edges), which the software renderer draws far faster than a
    textured ray."""
    j = np.arange(rows, dtype=np.int32)[None, :, None]
    k = np.arange(2, dtype=np.int32)[None, None, :]
    top_left = (np.arange(rays, dtype=np.int32) * (rows + 1) * 3)[:, None, None] + j * 3 + k
    cells = np.stack([top_left, top_left + 1, top_left + 4,
                      top_left, top_left + 4, top_left + 3], axis=-1)
    return cells.reshape(-1)


class Curtain:
    """A ring of rays around the zenith (see the module docstring)."""

    def __init__(self, rng, rays: int, radius: tuple, reach: tuple, folds: int,
                 strength: float, speed: float, tint=(1.0, 1.0, 1.0), profile=CURTAIN):
        self.rays = int(rays)
        self.rows = len(profile) - 1
        self.mesh = Mesh(self.rays * (self.rows + 1) * 3, _ray_indices(self.rays, self.rows))
        self.radius = radius
        self.reach = reach
        self.strength = strength
        self.speed = speed
        self.tint = np.asarray(tint, np.float32)
        # Rays bunch into folds of the curtain (where they overlap, the fold is brighter);
        # a few stand alone between them.
        centres = rng.random(folds)
        spread = rng.uniform(0.012, 0.05, folds)
        pick = rng.integers(folds, size=self.rays)
        u0 = centres[pick] + rng.normal(0.0, 1.0, self.rays) * spread[pick]
        alone = rng.random(self.rays) < 0.25
        u0[alone] = rng.random(int(alone.sum()))
        self.u0 = np.sort(u0 % 1.0).astype(np.float32)
        self.length = rng.uniform(0.7, 1.0, self.rays).astype(np.float32)   # each ray its own
        # The arc's shape, the rays' reach and the folds change slowly: one noise field
        # serves all three (each at its own offset), so a frame evaluates it once.
        self.slow = noise.Noise1D(rng, cells=7, octaves=3, time_cells=64)
        self.glints = noise.Noise1D(rng, cells=40, octaves=2, time_cells=256)
        self.waves = [(rng.uniform(1.0, 2.6), rng.uniform(0.004, 0.012), rng.uniform(0, 6.3),
                       rng.uniform(0.025, 0.06)) for _ in range(3)]
        self.fraction = np.array([f for f, _, _ in profile], np.float32)
        colors = np.array([c for _, c, _ in profile], np.float32) * self.tint
        self.colors = np.clip(colors, 0, 255).astype(np.uint8)
        self.alphas = np.array([a for _, _, a in profile], np.float32)

    def slow_fields(self, at: np.ndarray, u: np.ndarray, s: float) -> tuple:
        """(shape, reach) noise at arc positions ``at`` and fold noise at the rays ``u``,
        from one evaluation of the slow field."""
        n, m = len(at), len(u)
        x = np.concatenate([at, at + np.float32(0.37), u + np.float32(0.61)]).astype(np.float32)
        t = np.concatenate([np.full(n, s * 0.01), np.full(n, s * 0.008 + 17.0),
                            np.full(m, s * 0.012 + 31.0)]).astype(np.float32)
        cells = np.float32(self.slow.field.octaves[0].px)
        v = self.slow.field.at(x * cells, t)
        return v[:n], v[n:2 * n], v[2 * n:]

    def shape_at(self, u: np.ndarray, s: float, shape: np.ndarray, reach_noise: np.ndarray,
                 length) -> tuple:
        """(radius factor, reach towards the zenith) at positions ``u``; ``length`` is
        each ray's own share of the reach."""
        r = np.ones_like(u)
        for frequency, rate, phase, amplitude in self.waves:
            r += amplitude * np.sin(2 * math.pi * (frequency * u + rate * s) + phase)
        r += 0.06 * shape
        reach = self.reach[0] + (self.reach[1] - self.reach[0]) * np.clip(
            reach_noise * 0.9 + 0.5, 0, 1)
        return r, reach * length

    def edges(self, u: np.ndarray, r: np.ndarray, reach: np.ndarray, s: float, w: float,
              h: float, zx: float, zy: float):
        """(x, y) of every row of the rays at curtain positions ``u``: (rays, rows+1)."""
        theta = ARC[0] + (ARC[1] - ARC[0]) * u
        sway = 0.02 * np.sin(2 * math.pi * (u * 2.3 + s * 0.006))
        f = self.fraction[None, :]
        angle = theta[:, None] + sway[:, None] * f
        scale = (1.0 - reach[:, None] * f) * r[:, None]
        rx, ry = self.radius[0] * w, self.radius[1] * h
        return zx + np.cos(angle) * scale * rx, zy + np.sin(angle) * scale * ry

    def positions(self, s: float) -> np.ndarray:
        return (self.u0 + np.float32(s * 0.0015)) % np.float32(1.0)    # rays drift along the arc

    def rays_at(self, u: np.ndarray, s: float, activity: float, fold_noise: np.ndarray) -> tuple:
        """(half width, brightness) of the rays at positions ``u``."""
        glint = np.clip(self.glints.at(u, s * 0.03) * 1.3 + 0.5, 0, 1)
        half = (RAY_FILL[0] + (RAY_FILL[1] - RAY_FILL[0]) * glint) * (0.5 / RAY_REFERENCE)
        fold = np.clip(fold_noise * 0.9 + 0.6, 0, 1) ** 1.5
        share = min(1.0, RAY_REFERENCE / self.rays) ** 0.7
        brightness = np.clip(1.25 * fold * (0.5 + 0.5 * glint) * activity * self.strength * share,
                             0, 1.2)
        brightness *= np.clip(np.minimum(u, 1.0 - u) / 0.06, 0, 1)    # the arc's ends fade
        return half, brightness

    def along(self, positions: np.ndarray, t: float, activity: float, coarse: np.ndarray) -> tuple:
        """Software: (brightness, radius factor, reach) at arc ``positions`` (0..1): the
        rays' soft profiles summed, as overlapping rays add up on screen. The arc's shape
        changes slowly along it, so it is worked out at the ``coarse`` positions only."""
        s = t * self.speed
        u = self.positions(s)
        shape, reach_noise, folds = self.slow_fields(coarse, u, s)
        half, brightness = self.rays_at(u, s, activity, folds)
        d = np.abs(positions[None, :] - u[:, None])
        weight = np.maximum(0.0, 1.0 - d / half[:, None]) * brightness[:, None]
        light = weight.sum(axis=0)
        # Where rays overlap, the reach is that of the brightest of them, roughly.
        length = (weight * self.length[:, None]).sum(axis=0) / np.maximum(light, 1e-6)
        length = np.where(light > 1e-6, length, 0.85)
        r, reach = self.shape_at(coarse, s, shape, reach_noise, 1.0)
        r = np.interp(positions, coarse, r)
        reach = np.interp(positions, coarse, reach) * length
        return light.astype(np.float32), r.astype(np.float32), reach.astype(np.float32)

    def update_mesh(self, t: float, w: float, h: float, activity: float) -> None:
        s = t * self.speed
        zx, zy = ZENITH[0] * w, ZENITH[1] * h
        u = self.positions(s)
        shape, reach_noise, folds = self.slow_fields(u, u, s)
        half, brightness = self.rays_at(u, s, activity, folds)
        r, reach = self.shape_at(u, s, shape, reach_noise, self.length)   # once per ray
        lx, ly = self.edges(u - half, r, reach, s, w, h, zx, zy)
        mx, my = self.edges(u, r, reach, s, w, h, zx, zy)
        rx, ry = self.edges(u + half, r, reach, s, w, h, zx, zy)
        v = self.mesh.vertices.reshape(self.rays, self.rows + 1, 3)
        v["x"][..., 0], v["x"][..., 1], v["x"][..., 2] = lx, mx, rx
        v["y"][..., 0], v["y"][..., 1], v["y"][..., 2] = ly, my, ry
        for i, channel in enumerate("rgb"):
            v[channel] = self.colors[None, :, None, i]
        alpha = self.alphas[None, :] * brightness[:, None] * 255.0
        v["a"][..., 1] = np.clip(alpha, 0, 255).astype(np.uint8)     # the edges stay 0


class SoftwareCurtains:
    """The software renderer's curtains: a small image painted with NumPy each frame.

    For each curtain, every pixel's position around the zenith (its angle along the arc
    and its distance, in the curtain's own elliptical units) is worked out once. Each
    frame then needs only the brightness along the arc (the rays' profiles summed, at
    SOFTWARE_BINS points), the arc's radius and the rays' reach there; a pixel's light is
    that brightness times the colour and fade up the ray at its distance. The cost is per
    pixel of the small image, whatever the number of rays; all arrays are dense (NumPy's
    scattered writes are slow on a small ARM board)."""

    LUT = 256
    BORDER = 0.02               # the lower border fades in over this much of a ray (no jaggies)
    SHAPE_POINTS = 64           # the arc's slowly varying shape, sampled this often

    def __init__(self, curtains: list, sky: np.ndarray):
        self.curtains = curtains
        h, w = sky.shape[:2]
        self.base = [sky[..., i].astype(np.float32) for i in range(3)]
        self.image = np.empty((h, w, 4), np.uint8)
        self.image[..., 3] = 255
        self.positions = ((np.arange(SOFTWARE_BINS) + 0.5) / SOFTWARE_BINS).astype(np.float32)
        self.coarse = np.linspace(0.0, 1.0, self.SHAPE_POINTS).astype(np.float32)
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        zx, zy = ZENITH[0] * w, ZENITH[1] * h
        fractions = np.array([f for f, _, _ in CURTAIN])
        f = np.linspace(0.0, 1.0, self.LUT)
        self.alpha_lut = np.interp(f, fractions, [a for _, _, a in CURTAIN]).astype(np.float32)
        colors = np.array([c for _, c, _ in CURTAIN], np.float64)
        self.parts = []
        for curtain in curtains:
            nx = (x + 0.5 - zx) / (curtain.radius[0] * w)
            ny = (y + 0.5 - zy) / (curtain.radius[1] * h)
            rho = np.hypot(nx, ny)
            theta = np.arctan2(ny, nx)
            theta = np.where(theta < ARC[0], theta + 2 * math.pi, theta)
            along = (theta - ARC[0]) / (ARC[1] - ARC[0])
            outside = (along < 0) | (along >= 1)
            rho = np.where(outside, np.float32(1e3), rho)          # never lit
            bins = np.clip((along * SOFTWARE_BINS).astype(np.int32), 0, SOFTWARE_BINS - 1)
            luts = [(np.interp(f, fractions, colors[:, i]) * curtain.tint[i]).astype(np.float32)
                    for i in range(3)]
            # Only the rectangle the curtain can reach is painted.
            reach = rho < 1.0 + sum(a for *_, a in curtain.waves) + 0.08
            rows, cols = np.flatnonzero(reach.any(axis=1)), np.flatnonzero(reach.any(axis=0))
            if not len(rows):
                continue
            window = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
            self.parts.append((curtain, window, np.ascontiguousarray(bins[window]),
                               np.ascontiguousarray(rho[window].astype(np.float32)), luts))

    def paint(self, t: float, activity: float) -> np.ndarray:
        planes = [plane.copy() for plane in self.base]
        for curtain, window, bins, rho, luts in self.parts:
            light, r, reach = curtain.along(self.positions, t, activity, self.coarse)
            rr = r[bins]
            f = (rr - rho) * (1.0 / (r * reach))[bins]
            edge = np.clip((f + self.BORDER) * (1.0 / self.BORDER), 0.0, 1.0)
            edge *= f <= 1.0
            k = (np.clip(f, 0.0, 1.0) * (self.LUT - 1) + 0.5).astype(np.int32)
            level = light[bins] * np.maximum(self.alpha_lut[k], 0.5 * edge * (f < 0.05)) * edge
            for plane, lut in zip(planes, luts):
                plane[window] += level * lut[k]
        for i, plane in enumerate(planes):
            np.clip(plane, 0, 255, out=plane)
            self.image[..., i] = plane
        return self.image


class AuroraScene(Scene):
    id = "aurora"
    STARS = 900

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        tex = SOFTWARE_SCALE if self.software else min(1.0, q.texture + 0.25)
        self.sky_px = sky_gradient(ctx.rng("sky"), max(64, int(w * tex)), max(64, int(h * tex)), SKY)
        if self.software:       # the corona glow baked in: a big ADD pass a frame costs a lot
            self.sky_px = bake_glow(self.sky_px, GLOW_COLOR, GLOW_MEAN / 255.0)
        self.horizon_px = None
        if self.setting("mountains", True):
            hh = max(16, int(h * HORIZON))
            profile = ridge_line(ctx.rng("hills"), max(64, w), base=hh * 0.25, amplitude=hh * 0.3,
                                 cells=4)
            profile = add_trees(ctx.rng("trees"), profile, count=int(w / 18), height=hh * 0.45,
                                width_px=hh * 0.22, clustered=True)
            self.horizon_px = silhouette(np.minimum(profile, hh - 1), hh, (1, 2, 4),
                                         rim=(10, 26, 20), rim_width=1.2)
        detail = min(3, q.detail)
        rng = ctx.rng("curtains")
        self.curtains = [Curtain(rng, rays[detail], radius, reach, folds, strength, speed, tint)
                         for radius, reach, rays, folds, strength, speed, tint in CURTAINS]
        self.painter = SoftwareCurtains(self.curtains, self.sky_px) if self.software else None
        self.activity = noise.Noise1D(ctx.rng("activity"), cells=4, octaves=2, time_cells=32)
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, size=(1.3, 5.0), twinkle=0.35,
                               twinkle_speed=(0.1, 1.0), saturation=0.4)
        if self.gentle:
            self.stars.calm()
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.sky = self.upload(canvas, self.sky_px, NONE, "sky")
        self.horizon = self.upload(canvas, self.horizon_px, BLEND, "horizon") \
            if self.horizon_px is not None else None
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["soft"], ADD, "soft")
        self.grain.setup(self, canvas)
        self.sky_px = self.horizon_px = self.sprites = None

    def settings_changed(self, keys: set) -> bool:
        return "mountains" in keys

    def level(self, t: float) -> float:
        """Overall activity 0.45..1.0, changing over minutes."""
        a = float(self.activity.at(np.array([0.3], np.float32), t * 0.004)[0])
        return 0.45 + 0.55 * min(1.0, max(0.0, a * 1.2 + 0.55))

    def draw(self, canvas) -> None:
        w, h, t = self.width, self.height, self.t
        activity = self.level(t)
        motion = t * (CURTAIN_GENTLE if self.gentle else 1.0)
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        if self.painter is not None:
            # Sky, corona and curtains in one small image, scaled up; stars added on top
            # (aurora light is transparent: stars shine through it).
            canvas.update(self.sky, self.painter.paint(motion, activity))
            canvas.image(self.sky, 0, 0, w, h)
            self.stars.draw(canvas, self.star_tex, t, w, h, count=count, alpha=0.7)
        else:
            canvas.image(self.sky, 0, 0, w, h)
            self.stars.draw(canvas, self.star_tex, t, w, h, count=count, alpha=0.7)
            canvas.centered(self.glow_tex, ZENITH[0] * w, ZENITH[1] * h, h * 0.9, h * 0.9,
                            color=GLOW_COLOR, alpha=int(GLOW_PEAK * activity))
            for curtain in self.curtains:
                curtain.update_mesh(motion, w, h, activity)
                curtain.mesh.draw(canvas, None, ADD)
        if self.horizon is not None:
            canvas.image(self.horizon, 0, h - self.horizon.height, w, self.horizon.height)
        self.grain.draw(canvas)
