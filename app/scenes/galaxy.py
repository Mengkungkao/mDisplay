"""Scene A — Deep-space galaxy: a spiral galaxy turning slowly, seen at an angle.

The disk is generated face-on (logarithmic spiral arms, a warm bulge, dust
lanes on the inner edge of the arms, pink star-forming knots, sprinkled
stars), turned in its own plane into a square render target, then drawn
foreshortened and tilted, so it rotates like an inclined disk rather than a
spinning picture. Bright disk stars orbit faster near the centre than at
the edge. A slow camera sway moves the galaxy against the background more
than the distant stars: parallax.

Illustrative, not an astronomical model.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise, sprites
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, BLEND, NONE
from ..gfx.palette import star_colors
from .base import Scene
from .parts import Grain, StarField, common_sprites, density_count, sky_gradient

INCLINATION = math.radians(63.0)     # 0 = face-on
TILT = -21.0                         # degrees, on screen
TURN_SECONDS = 1500.0                # one turn of the arm pattern at speed 1


def galaxy_disk(rng: np.random.Generator, size: int, detail: int) -> np.ndarray:
    """A face-on spiral galaxy as straight-alpha RGBA (drawn additively)."""
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (xx - c) / (size / 2.0), (yy - c) / (size / 2.0)
    r = np.hypot(dx, dy)
    theta = np.arctan2(dy, dx)
    # Arm phase on a logarithmic spiral, perturbed by noise so arms are irregular.
    pitch = math.radians(rng.uniform(19.0, 24.0))
    warp = noise.FBM(rng, 4, 4, 3 + detail)
    u, v = (dx + 1.0) * 2.0, (dy + 1.0) * 2.0
    perturb = warp.at(u, v) * 0.55
    phase = theta - np.log(np.maximum(r, 0.02)) / math.tan(pitch) + perturb
    arms = (0.5 + 0.5 * np.cos(2.0 * phase)) ** 2.6
    spur = (0.5 + 0.5 * np.cos(2.0 * phase + 1.1 + perturb * 2)) ** 6 * 0.35
    lane = (0.5 + 0.5 * np.cos(2.0 * phase - 0.62)) ** 9                  # inner edge of each arm
    fine = noise.FBM(rng, 12, 12, 3 + detail)
    clump = noise.contrast(fine.at(u * 3.0, v * 3.0) * 0.5 + 0.5, 0.45, 0.85)
    dusty = noise.contrast(fine.at(u * 2.0 + 7.1, v * 2.0 + 3.3) * 0.5 + 0.5, 0.35, 0.7)
    ring_in = np.clip((r - 0.06) / 0.12, 0, 1)
    edge = np.clip((1.0 - r) / 0.25, 0, 1) ** 1.5
    disk = np.exp(-r / 0.3) * edge
    bulge = np.exp(-(r / 0.075) ** 0.9) * 0.95
    arm_light = (arms * (0.55 + 0.75 * clump) + spur) * ring_in * edge * np.exp(-r / 0.55)
    light = disk * 0.5 + bulge + arm_light * 0.9
    dust = lane * ring_in * edge * (0.45 + 0.55 * dusty)
    light *= 1.0 - 0.72 * np.clip(dust * 1.4, 0, 1)
    # Colour: warm bulge, white disk, blue-white arms, pink knots in the arms.
    knots = noise.contrast(fine.at(u * 6.0 + 1.7, v * 6.0) * 0.5 + 0.5, 0.62, 0.8) * arms * ring_in
    rgb = np.empty((size, size, 3), np.float32)
    warmth = np.clip(bulge / 0.95 + disk * 0.5, 0, 1)
    rgb[..., 0] = 0.62 + 0.38 * warmth
    rgb[..., 1] = 0.76 + 0.10 * warmth
    rgb[..., 2] = 1.0 - 0.42 * warmth
    pink = np.array([1.0, 0.45, 0.7], np.float32)
    rgb += (pink - rgb) * np.clip(knots * 0.9, 0, 1)[..., None]
    alpha = np.clip(light * 0.85, 0, 1)
    alpha += np.clip(knots * 0.35 * edge, 0, 0.35)
    # Sprinkle resolved stars along the light, one or two pixels each.
    count = int(size * size * 0.012)
    weights = (arm_light + disk * 0.3).ravel()
    weights = weights / weights.sum()
    picks = rng.choice(size * size, count, p=weights)
    bright = rng.random(count).astype(np.float32) ** 3 * 0.9 + 0.1
    flat = alpha.reshape(-1)
    np.add.at(flat, picks, bright)
    flat_rgb = rgb.reshape(-1, 3)
    flat_rgb[picks] = flat_rgb[picks] * 0.4 + 0.6 * np.array([0.92, 0.95, 1.0], np.float32)
    alpha = np.clip(alpha, 0, 1)
    return sprites.rgba(np.clip(rgb, 0, 1), alpha)


def tiny_galaxy(rng: np.random.Generator, size: int = 64) -> np.ndarray:
    """A distant galaxy: a small soft ellipse with a brighter core."""
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    ratio = rng.uniform(0.25, 0.8)
    r = np.hypot((xx - c) / (size / 2.0), (yy - c) / (size / 2.0 * ratio))
    alpha = np.exp(-(r / 0.35) ** 1.2) * np.clip(1 - r, 0, 1)
    warm = rng.uniform(0, 1)
    rgb = np.empty((size, size, 3), np.float32)
    rgb[...] = (0.85 + 0.15 * warm, 0.85, 1.0 - 0.2 * warm)
    return sprites.rgba(rgb, np.clip(alpha, 0, 1))


class GalaxyScene(Scene):
    id = "galaxy"
    STARS = 1100
    DISK_STARS = 260

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        self.diameter_factor = 1.5
        size = ctx.texture_size(1400, minimum=256)
        size = min(size, int(min(w, h) * self.diameter_factor * 1.15), ctx.max_texture)
        self.disk_size = max(256, size)
        rng = ctx.rng("galaxy")
        self.disk_px = galaxy_disk(rng, self.disk_size, q.detail)
        gw, gh = max(64, int(w * min(1.0, q.texture + 0.25))), max(64, int(h * min(1.0, q.texture + 0.25)))
        self.back_px = sky_gradient(ctx.rng("space"), gw, gh,
                                    [(0.0, (3, 3, 10)), (0.5, (6, 5, 16)), (1.0, (3, 4, 11))],
                                    dither=1.0)
        self.tiny_px = [tiny_galaxy(ctx.rng(f"tiny{i}")) for i in range(3)]
        trng = ctx.rng("tiny-pos")
        self.tiny = [(trng.uniform(0.03, 0.97), trng.uniform(0.04, 0.96), trng.uniform(0.012, 0.03),
                      trng.uniform(0, 360), int(trng.integers(3)), trng.uniform(0.35, 0.7))
                     for _ in range(9)]
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, size=(1.3, 5.5), twinkle=0.25,
                               twinkle_speed=(0.05, 0.6), saturation=0.5)
        # Disk stars on circular orbits: flat rotation curve, so inner ones go round faster.
        drng = ctx.rng("disk-stars")
        n = int(self.DISK_STARS * max(0.5, q.stars))
        self.orbit_r = (0.12 + 0.8 * drng.random(n) ** 0.8).astype(np.float32)
        self.orbit_a = drng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.orbit_b = (drng.random(n) ** 2.5 * 0.85 + 0.15).astype(np.float32)
        self.orbit_c = star_colors(drng, n, 0.55, warm=0.35)
        self.orbit_batch = QuadBatch(n)
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)
        self.sprites["core"] = sprites.glow(256, 2.6, core=1.0)

    def setup(self, canvas) -> None:
        self.disk = self.upload(canvas, self.disk_px, NONE, "disk")
        self.frame = canvas.target(self.disk_size, self.disk_size, "galaxy.frame", ADD)
        self.textures.append(self.frame)
        self.back = self.upload(canvas, self.back_px, BLEND, "space")
        self.tiny_tex = [self.upload(canvas, px, ADD, f"tiny{i}") for i, px in enumerate(self.tiny_px)]
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.core_tex = self.upload(canvas, self.sprites["core"], ADD, "core")
        self.soft_tex = self.upload(canvas, self.sprites["soft"], ADD, "soft")
        self.grain.setup(self, canvas)
        self.disk_px = self.back_px = self.tiny_px = self.sprites = None

    def draw(self, canvas) -> None:
        w, h, t, u = self.width, self.height, self.t, self.unit
        canvas.image(self.back, 0, 0, w, h)
        sway_x = math.sin(t / 97.0) * 0.018 * w + math.sin(t / 41.0) * 0.004 * w
        sway_y = math.sin(t / 131.0) * 0.012 * h
        # Distant galaxies and stars move less than the galaxy: parallax.
        for x, y, scale, angle, kind, a in self.tiny:
            size = scale * min(w, h) * 2.2
            canvas.centered(self.tiny_tex[kind], x * w + sway_x * 0.2, y * h + sway_y * 0.2, size,
                            size, angle, alpha=int(255 * a))
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, offset_x=sway_x * 0.3,
                        offset_y=sway_y * 0.3, wrap=True, alpha=0.9)
        cx, cy = w * 0.5 + sway_x, h * 0.5 + sway_y
        diameter = min(w, h) * self.diameter_factor
        if w < h:                                   # portrait: keep the long axis on screen
            diameter = w * 1.15
        squash = math.cos(INCLINATION)
        angle = (t / TURN_SECONDS) * 360.0
        breathing = 0.93 + 0.07 * math.sin(t / 23.0) + 0.03 * math.sin(t / 7.3)
        tint = (255, int(244 + 8 * math.sin(t / 61.0)), 255)
        glow = float(self.setting("nebula_intensity", 1.0))
        # Turn the disk in its own plane, then draw it foreshortened and tilted.
        s = self.disk_size
        with canvas.into(self.frame):
            canvas.clear((0, 0, 0), alpha=0)
            canvas.image(self.disk, 0, 0, s, s, angle=angle)
        level = min(255, int(255 * (0.35 + 0.65 * glow) * breathing))
        canvas.centered(self.frame, cx, cy, diameter, diameter * squash, TILT,
                        color=tint, alpha=level)
        # Core glow, gently breathing.
        core = diameter * 0.42
        canvas.centered(self.core_tex, cx, cy, core, core * (0.55 + 0.45 * squash), TILT,
                        color=(255, 222, 176), alpha=int(110 * breathing))
        canvas.centered(self.soft_tex, cx, cy, diameter * 0.95, diameter * 0.95 * squash, TILT,
                        color=(120, 130, 200), alpha=int(36 * (0.4 + 0.6 * glow)))
        self._draw_disk_stars(canvas, cx, cy, diameter, squash, angle)
        self.grain.draw(canvas)

    def _draw_disk_stars(self, canvas, cx, cy, diameter, squash, pattern_angle) -> None:
        t = self.t
        n = len(self.orbit_r)
        omega = (2 * math.pi / TURN_SECONDS) * 0.55 / np.maximum(self.orbit_r, 0.12)
        a = self.orbit_a + omega * np.float32(t)
        x = np.cos(a) * self.orbit_r * np.float32(diameter * 0.5)
        y = np.sin(a) * self.orbit_r * np.float32(diameter * 0.5 * squash)
        tilt = math.radians(TILT)
        px = cx + x * math.cos(tilt) - y * math.sin(tilt)
        py = cy + x * math.sin(tilt) + y * math.cos(tilt)
        size = np.float32(self.unit) * (2.0 + 7.0 * self.orbit_b)
        twinkle = 0.85 + 0.15 * np.sin(np.float32(t) * (0.6 + self.orbit_b) + self.orbit_a * 7.0)
        alpha = 255.0 * self.orbit_b * twinkle * np.clip((self.orbit_r - 0.1) / 0.1, 0, 1)
        self.orbit_batch.sprites(px, py, size, size, self.orbit_c, alpha)
        self.orbit_batch.draw(canvas, self.star_tex, ADD, n)
