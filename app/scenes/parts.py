"""Shared scene parts: star fields, meteors, skies, silhouettes and film grain.

Scenes compose these instead of repeating them; each part keeps its own
preallocated buffers, so drawing allocates nothing per frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..gfx import noise, palette, sprites
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, Canvas, Texture

TAU = 2.0 * math.pi


# ------------------------------------------------------------------ stars

class StarField:
    """Stars with individual brightness, colour and twinkle, drawn in one call.

    Positions are normalised (0..1) inside ``region`` (x0, y0, x1, y1), so the
    field fits any output size. ``count`` is the most that will be drawn;
    ``draw(count=...)`` draws fewer (the star-density setting) without
    regenerating, and the stars are in random order so any prefix is an even
    sample.
    """

    def __init__(self, rng: np.random.Generator, count: int, region=(0.0, 0.0, 1.0, 1.0),
                 size=(1.4, 6.5), twinkle: float = 0.35, twinkle_speed=(0.08, 0.9),
                 saturation: float = 0.5, faintness: float = 3.2, warm: float = 0.5,
                 y_weight=None, positions=None):
        n = max(1, int(count)) if positions is None else len(positions[0])
        self.n = n
        x0, y0, x1, y1 = region
        self.x = (x0 + (x1 - x0) * rng.random(n)).astype(np.float32)
        if positions is not None:
            self.x = np.asarray(positions[0], np.float32)
            ys = (np.asarray(positions[1], np.float32) - y0) / max(1e-6, y1 - y0)
        elif y_weight is None:
            ys = rng.random(n)
        else:
            # More stars where y_weight(y) is high (e.g. away from a hazy horizon).
            candidates = rng.random(n * 4)
            keep = rng.random(n * 4) < y_weight(candidates)
            ys = candidates[keep][:n]
            if len(ys) < n:
                ys = np.concatenate([ys, rng.random(n - len(ys))])
        self.y = (y0 + (y1 - y0) * ys).astype(np.float32)
        self.b = (rng.random(n) ** faintness).astype(np.float32)          # most stars faint
        self.colors = palette.star_colors(rng, n, saturation, warm)
        self.f1 = rng.uniform(twinkle_speed[0], twinkle_speed[1], n).astype(np.float32)
        self.f2 = (rng.uniform(twinkle_speed[0], twinkle_speed[1], n) * 1.73).astype(np.float32)
        self.p1 = rng.uniform(0, TAU, n).astype(np.float32)
        self.p2 = rng.uniform(0, TAU, n).astype(np.float32)
        self.depth = (twinkle * rng.uniform(0.25, 1.0, n)).astype(np.float32)
        self.size_lo, self.size_hi = size
        self.batch = QuadBatch(n)

    def twinkle(self, t: float, n: int, depth_scale=None) -> np.ndarray:
        a = 0.5 + 0.5 * np.sin(self.f1[:n] * np.float32(TAU * t) + self.p1[:n])
        b = 0.5 + 0.5 * np.sin(self.f2[:n] * np.float32(TAU * t) + self.p2[:n])
        depth = self.depth[:n] if depth_scale is None else self.depth[:n] * depth_scale
        return 1.0 - depth * a * b

    def positions(self, width: float, height: float, n: int, offset_x: float = 0.0,
                  offset_y: float = 0.0, wrap: bool = False) -> tuple:
        px = self.x[:n] * np.float32(width) + np.float32(offset_x)
        py = self.y[:n] * np.float32(height) + np.float32(offset_y)
        if wrap:
            px = np.mod(px, np.float32(width))
        return px, py

    def draw(self, canvas: Canvas, texture: Texture, t: float, width: float, height: float,
             alpha: float = 1.0, count=None, offset_x: float = 0.0, offset_y: float = 0.0,
             wrap: bool = False, size_scale: float = 1.0, twinkle_scale=None,
             positions=None, blend: int = ADD) -> int:
        n = self.n if count is None else max(0, min(self.n, int(count)))
        if n == 0 or alpha <= 0:
            return 0
        if positions is None:
            px, py = self.positions(width, height, n, offset_x, offset_y, wrap)
        else:
            px, py = positions[0][:n], positions[1][:n]
        unit = min(width, height) / 1080.0
        b = self.b[:n]
        size = np.float32(unit * size_scale) * (self.size_lo + (self.size_hi - self.size_lo)
                                                * b ** 1.35)
        size = np.maximum(size, np.float32(1.6))
        depth_scale = twinkle_scale(py) if callable(twinkle_scale) else twinkle_scale
        a = (np.float32(30.0) + np.float32(225.0) * b ** 0.55) * self.twinkle(t, n, depth_scale)
        a *= np.float32(alpha)
        self.batch.sprites(px, py, size * 0.5, size * 0.5, self.colors[:n], a)
        self.batch.draw(canvas, texture, blend)
        return n


def density_count(base: int, quality, density: float) -> tuple:
    """(capacity, drawn) star counts for a base count at 1080p."""
    capacity = max(8, int(base * quality.stars * 2.0))
    drawn = max(4, int(base * quality.stars * max(0.0, density)))
    return capacity, min(capacity, drawn)


# ----------------------------------------------------------------- meteors

@dataclass
class Meteor:
    x: float
    y: float
    angle: float
    speed: float
    length: float
    life: float
    brightness: float
    width: float
    age: float = 0.0


class Meteors:
    """Meteor trails with a Poisson spawn rate, a cap on how many fly at once
    and a minimum gap, so they stay occasional and never flash in bursts.

    ``per_minute`` is the rate at frequency 1.0; the meteor-frequency setting
    multiplies it (0 = none). With ``radiant`` (normalised x, y) the trails
    point away from it and are shorter near it, as in a real shower.
    """

    def __init__(self, rng: np.random.Generator, per_minute: float = 2.0, max_active: int = 2,
                 min_gap: float = 3.0, speed=(0.35, 0.75), length=(0.07, 0.2), life=(0.55, 1.2),
                 angles=((20, 65), (115, 160)), area=(0.05, 0.03, 0.95, 0.6), radiant=None,
                 brightness=(0.45, 0.9), fireball: float = 0.03, color=(255, 246, 232),
                 width=4.4):
        self.rng = rng
        self.per_minute = per_minute
        self.max_active = max(1, int(max_active))
        self.min_gap = min_gap
        self.speed = speed
        self.length = length
        self.life = life
        self.angles = angles
        self.area = area
        self.radiant = radiant
        self.brightness = brightness
        self.fireball = fireball
        self.color = color
        self.width = width
        self.active: list = []
        self.since_last = min_gap
        self.spawned = 0
        self.trails = QuadBatch(self.max_active)
        self.heads = QuadBatch(self.max_active)

    def rate(self, frequency: float) -> float:
        """Expected meteors per second."""
        return max(0.0, self.per_minute * frequency) / 60.0

    def update(self, dt: float, frequency: float, width: float, height: float) -> None:
        if dt <= 0:
            return
        for meteor in self.active:
            meteor.age += dt
        self.active = [m for m in self.active if m.age < m.life]
        self.since_last += dt
        rate = self.rate(frequency)
        if rate <= 0 or len(self.active) >= self.max_active or self.since_last < self.min_gap:
            return
        if self.rng.random() < 1.0 - math.exp(-rate * dt):
            self.spawn(width, height)

    def spawn(self, width: float, height: float) -> Meteor:
        rng = self.rng
        diag = math.hypot(width, height)
        x0, y0, x1, y1 = self.area
        x = (x0 + (x1 - x0) * rng.random()) * width
        y = (y0 + (y1 - y0) * rng.random()) * height
        length = rng.uniform(*self.length) * diag
        if self.radiant is not None:
            rx, ry = self.radiant[0] * width, self.radiant[1] * height
            angle = math.atan2(y - ry, x - rx)
            distance = math.hypot(x - rx, y - ry)
            length *= min(1.0, max(0.2, 2.2 * distance / diag))
        else:
            lo, hi = self.angles[int(rng.integers(len(self.angles)))]
            angle = math.radians(rng.uniform(lo, hi))
        big = rng.random() < self.fireball
        meteor = Meteor(x, y, angle, rng.uniform(*self.speed) * diag, length,
                        rng.uniform(*self.life) * (1.5 if big else 1.0),
                        1.0 if big else rng.uniform(*self.brightness),
                        self.width * (1.7 if big else rng.uniform(0.8, 1.2)))
        self.active.append(meteor)
        self.since_last = 0.0
        self.spawned += 1
        return meteor

    @staticmethod
    def envelope(meteor: Meteor) -> float:
        p = meteor.age / meteor.life
        rise = min(1.0, p / 0.12)
        fall = 1.0 if p < 0.45 else max(0.0, 1.0 - (p - 0.45) / 0.55) ** 1.6
        return rise * rise * (3 - 2 * rise) * fall

    def draw(self, canvas: Canvas, streak: Texture, glow: Texture, unit: float,
             alpha: float = 1.0) -> None:
        n = len(self.active)
        if not n or alpha <= 0:
            return
        hx = np.empty(n, np.float32)
        hy = np.empty(n, np.float32)
        ang = np.empty(n, np.float32)
        length = np.empty(n, np.float32)
        width = np.empty(n, np.float32)
        a = np.empty(n, np.float32)
        for i, m in enumerate(self.active):
            travelled = m.speed * m.age
            hx[i] = m.x + math.cos(m.angle) * travelled
            hy[i] = m.y + math.sin(m.angle) * travelled
            ang[i] = m.angle
            # The visible trail grows behind the head, then the tail catches up as it fades.
            length[i] = max(2.0, min(travelled, m.length) * (0.55 + 0.45 * self.envelope(m)))
            width[i] = m.width * unit * 0.5
            a[i] = 255.0 * self.envelope(m) * m.brightness * alpha
        self.trails.streaks(hx, hy, ang, length, width, self.color, a)
        self.trails.draw(canvas, streak, ADD)
        glow_size = np.float32(16.0 * unit) * (width / max(1e-3, self.width * unit * 0.5))
        self.heads.sprites(hx, hy, glow_size, glow_size, self.color, a * 0.45)
        self.heads.draw(canvas, glow, ADD)


# ------------------------------------------------------------------- skies

def sky_gradient(rng: np.random.Generator, width: int, height: int, stops: list,
                 dither: float = 1.0) -> np.ndarray:
    """An opaque vertical gradient with dithering, so dark skies show no banding.

    ``stops`` = [(position 0..1 from the top, (r, g, b))].
    """
    pos = np.array([p for p, _ in stops], np.float32)
    cols = np.array([c for _, c in stops], np.float32)
    t = (np.arange(height, dtype=np.float32) + 0.5) / np.float32(height)
    column = np.stack([np.interp(t, pos, cols[:, k]) for k in range(3)], axis=-1)
    image = np.empty((height, width, 4), np.uint8)
    jitter = (rng.random((height, width, 1), dtype=np.float32) - 0.5) * np.float32(2.0 * dither)
    image[..., :3] = np.clip(column[:, None, :] + jitter + 0.5, 0, 255).astype(np.uint8)
    image[..., 3] = 255
    return image


def grain(rng: np.random.Generator, size: int = 256, strength: float = 2.2) -> np.ndarray:
    """A small tileable noise tile, drawn additively with a fresh offset each frame:
    temporal dithering that dissolves banding in dark gradients."""
    value = rng.random((size, size), dtype=np.float32) * np.float32(strength)
    image = np.zeros((size, size, 4), np.uint8)
    image[..., 0] = image[..., 1] = image[..., 2] = np.clip(value + 0.5, 0, 255).astype(np.uint8)
    image[..., 3] = 255
    return image


class Grain:
    """Film grain for scenes with large dark gradients (GPU renderers only: on the
    software renderer the extra full-screen pass costs more than it gives)."""

    def __init__(self, rng: np.random.Generator, enabled: bool):
        self.rng = rng
        self.pixels = grain(rng) if enabled else None
        self.texture = None

    def setup(self, scene, canvas: Canvas) -> None:
        if self.pixels is not None and canvas.accelerated:
            self.texture = scene.upload(canvas, self.pixels, ADD, "grain", linear=False)

    def draw(self, canvas: Canvas) -> None:
        if self.texture is None:
            return
        ox, oy = self.rng.integers(0, 256, 2)
        canvas.tiled(self.texture, -float(ox), -float(oy), 256, 256)


def ridge_line(rng: np.random.Generator, width: int, base: float, amplitude: float,
               cells: int = 6, octaves: int = 5, ridged: bool = False) -> np.ndarray:
    """A 1-D height profile (pixels from the bottom) across ``width`` columns."""
    field = noise.FBM(rng, cells, 1, octaves, 0.5)
    u = (np.arange(width, dtype=np.float32) + 0.5) * np.float32(cells / width)
    n = field.at(u, np.zeros_like(u), ridged=ridged)
    if not ridged:
        n = n * 0.5 + 0.5
    n = (n - n.min()) / max(1e-6, float(n.max() - n.min()))
    return np.float32(base) + np.float32(amplitude) * n


def add_trees(rng: np.random.Generator, profile: np.ndarray, count: int, height: float,
              width_px: float, clustered: bool = False) -> np.ndarray:
    """Conifer silhouettes standing on a profile; ``clustered`` groups them with clearings."""
    out = profile.copy()
    w = len(profile)
    xs = np.arange(w, dtype=np.float32)
    groves = noise.FBM(rng, 6, 1, 3) if clustered else None
    placed = 0
    for _ in range(int(count) * 4):
        if placed >= count:
            break
        cx = rng.uniform(0, w)
        if groves is not None:
            g = float(groves.at(np.float32(cx / w * 6), np.float32(0.5)))
            if rng.random() > np.clip(g * 1.6 + 0.35, 0.0, 1.0):
                continue
        placed += 1
        h = height * rng.uniform(0.35, 1.0)
        half = width_px * rng.uniform(0.6, 1.2) * 0.5
        lo, hi = int(max(0, cx - half)), int(min(w, cx + half + 1))
        if hi <= lo:
            continue
        local = xs[lo:hi]
        shape = h * np.clip(1.0 - np.abs(local - cx) / half, 0, 1) ** 1.15
        # Small jags along the edges, like branches.
        shape *= 1.0 - 0.12 * (np.sin((local - cx) * 1.3 + cx) > 0.6)
        base = profile[int(min(w - 1, max(0, cx)))]
        out[lo:hi] = np.maximum(out[lo:hi], base + shape)
    return out


def silhouette(profile: np.ndarray, height: int, rgb=(0, 0, 0), alpha: float = 1.0,
               rim=None, rim_width: float = 2.0) -> np.ndarray:
    """An RGBA image whose bottom part, below ``profile`` (pixels from the bottom), is solid.

    Edges are anti-aliased; ``rim`` (r, g, b) adds a faint lit edge.
    """
    width = len(profile)
    rows = (height - 1 - np.arange(height, dtype=np.float32))[:, None]   # pixels from the bottom
    coverage = np.clip(profile[None, :] - rows + 0.5, 0, 1)
    image = np.zeros((height, width, 4), np.uint8)
    color = np.empty((height, width, 3), np.float32)
    color[...] = np.asarray(rgb, np.float32)
    if rim is not None:
        edge = np.clip(1.0 - (profile[None, :] - rows) / rim_width, 0, 1) * coverage
        color += (np.asarray(rim, np.float32) - np.asarray(rgb, np.float32)) * edge[..., None]
    image[..., :3] = np.clip(color + 0.5, 0, 255).astype(np.uint8)
    image[..., 3] = np.clip(coverage * alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return image


# ----------------------------------------------------------- common sprites

def common_sprites(quality) -> dict:
    """The sprite set most scenes share (generated once per scene preparation)."""
    return {
        "star": sprites.star(32),
        "spike": sprites.spiked_star(96 if quality.detail >= 1 else 64),
        "glow": sprites.glow(128, 2.2, core=0.6),
        "soft": sprites.glow(256, 1.6),
        "streak": sprites.streak(256, 16),
    }
