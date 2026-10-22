"""Scene E — Solar system: the Sun and the eight planets, seen from above at an angle.

What is real and what is not, said on screen when planet names are on:
  * the planets *start* at their approximate heliocentric longitudes for the
    current date (JPL mean elements, see astro.py);
  * from then on the motion is sped up (a year passes in about a minute;
    outer planets are slowed less than in reality so they visibly move);
  * distances and sizes are compressed, not to scale.

Each planet is lit from the Sun: its day side turns towards the Sun as it
orbits. Saturn's rings pass behind and in front of the planet.
"""

from __future__ import annotations

import math
import time

import numpy as np
from PIL import Image, ImageDraw

from ..gfx import noise, sprites
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, BLEND, MOD
from ..ui import text as textlib
from . import astro
from .base import Scene
from .parts import StarField, common_sprites, density_count

SQUASH = 0.36                      # orbit ellipses: vertical / horizontal
EARTH_YEAR_SECONDS = 60.0          # at speed 1

# id, name, real semi-major axis (au), real period (years), size at 1080p (px), colours
PLANETS = (
    ("mercury", "Mercury", 0.387, 0.241, 7, ((150, 144, 140), (110, 104, 100))),
    ("venus", "Venus", 0.723, 0.615, 11, ((236, 214, 168), (210, 180, 130))),
    ("earth", "Earth", 1.0, 1.0, 12, ((60, 110, 210), (90, 150, 90))),
    ("mars", "Mars", 1.524, 1.881, 9, ((205, 104, 64), (160, 80, 50))),
    ("jupiter", "Jupiter", 5.203, 11.86, 30, ((214, 184, 150), (170, 120, 90))),
    ("saturn", "Saturn", 9.537, 29.46, 25, ((226, 202, 150), (190, 160, 110))),
    ("uranus", "Uranus", 19.19, 84.01, 17, ((160, 220, 226), (130, 196, 206))),
    ("neptune", "Neptune", 30.07, 164.8, 16, ((70, 110, 220), (50, 80, 180))),
)


def orbit_fraction(au: float) -> float:
    """Compressed distance: 0..1 of the largest orbit."""
    return (0.18 + 0.82 * (au / 30.07) ** 0.5) if au > 0 else 0.0


def angular_speed(period_years: float) -> float:
    """Radians per scene second; outer planets slowed less than in reality (illustrative)."""
    return 2 * math.pi / (EARTH_YEAR_SECONDS * period_years ** 0.55)


def planet_surface(rng, key: str, colors, size: int) -> np.ndarray:
    """A lit-from-nowhere disc with bands or patches (shading is a separate layer)."""
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (xx - c) / (size / 2.0), (yy - c) / (size / 2.0)
    r = np.hypot(dx, dy)
    a, b = np.array(colors[0], np.float32) / 255, np.array(colors[1], np.float32) / 255
    field = noise.FBM(rng, 4, 4, 4)
    n = field.at((dx + 1) * 2, (dy + 1) * 2) * 0.5 + 0.5
    if key in ("jupiter", "saturn"):
        bands = 0.5 + 0.5 * np.sin(dy * (14 if key == "jupiter" else 10) + n * 2.5)
        mix = bands * 0.8 + n * 0.2
    elif key == "earth":
        mix = noise.contrast(n, 0.5, 0.56)          # land and sea
    else:
        mix = n
    rgb = a + (b - a) * mix[..., None]
    if key == "earth":
        clouds = noise.contrast(field.at((dx + 1) * 4 + 3, (dy + 1) * 4) * 0.5 + 0.5, 0.55, 0.75)
        rgb += (1.0 - rgb) * (clouds * 0.7)[..., None]
    if key == "jupiter":
        spot = np.exp(-(((dx - 0.25) / 0.16) ** 2 + ((dy - 0.3) / 0.08) ** 2))
        rgb += (np.array([0.75, 0.4, 0.3], np.float32) - rgb) * (spot * 0.8)[..., None]
    alpha = np.clip((1.0 - r) * size / 2.0, 0, 1)
    return sprites.rgba(np.clip(rgb, 0, 1), alpha)


def shading(size: int) -> np.ndarray:
    """Multiply layer, lit from +x: white day side, dark night side, white outside the disc."""
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (xx - c) / (size / 2.0), (yy - c) / (size / 2.0)
    r2 = dx * dx + dy * dy
    nz = np.sqrt(np.clip(1.0 - r2, 0, 1))
    lambert = np.clip(dx * 0.85 + nz * 0.35, 0, 1)
    light = 0.08 + 0.92 * lambert ** 0.8
    inside = np.clip((1.0 - np.sqrt(r2)) * size / 2.0, 0, 1)
    value = 1.0 - inside * (1.0 - light)
    image = np.empty((size, size, 4), np.uint8)
    image[..., :3] = np.clip(value * 255 + 0.5, 0, 255).astype(np.uint8)[..., None]
    image[..., 3] = 255
    return image


def rings(size: int) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot((xx - c) / (size / 2.0), (yy - c) / (size / 2.0 * SQUASH * 1.25))
    band = np.clip((r - 0.52) / 0.04, 0, 1) * np.clip((0.98 - r) / 0.04, 0, 1)
    gaps = 1.0 - 0.7 * np.exp(-((r - 0.78) / 0.015) ** 2)
    stripes = 0.75 + 0.25 * np.sin(r * 90.0)
    alpha = band * gaps * stripes * 0.85
    rgb = np.empty((size, size, 3), np.float32)
    rgb[...] = (0.88, 0.8, 0.64)
    return sprites.rgba(rgb, np.clip(alpha, 0, 1))


class SolarSystemScene(Scene):
    id = "solar"
    STARS = 900

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        tex = 96 if q.detail >= 1 else 64
        rng = ctx.rng("planets")
        self.surface_px = {key: planet_surface(rng, key, colors, tex)
                           for key, _n, _a, _p, _s, colors in PLANETS}
        self.shade_px = shading(tex)
        self.rings_px = rings(256 if q.detail >= 1 else 160)
        self.sun_px = sprites.disc(128, 2.0)
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, size=(1.3, 5.0), twinkle=0.2,
                               twinkle_speed=(0.05, 0.5), saturation=0.45)
        # Where the planets really are now (approximately); then illustrative motion.
        now = ctx.wall_clock()
        self.start_date = now
        self.real_start = astro.in_valid_range(now)
        start = {}
        for key, *_ in PLANETS:
            if self.real_start:
                start[key] = math.radians(astro.longitude(key, now))
            else:
                start[key] = rng.uniform(0, 2 * math.pi)
        self.start = start
        brng = ctx.rng("belt")
        n = int(500 * max(0.5, q.stars))
        self.belt_r = brng.uniform(orbit_fraction(2.1), orbit_fraction(3.3), n).astype(np.float32)
        self.belt_a = brng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.belt_b = (brng.random(n) * 0.6 + 0.2).astype(np.float32)
        self.belt_batch = QuadBatch(n)
        self.sprites = common_sprites(q)
        self.sprites["corona"] = sprites.glow(256, 1.4)
        self._layout(self.width, self.height)
        self.orbit_px = self._orbits_image() if self.setting("orbits", True) else None

    def _label_images(self) -> dict:
        """Planet names and the honesty note (rendered on the render thread: FreeType
        faces are not shared across threads)."""
        if not self.setting("planet_labels", False):
            return {}
        size = max(12, int(17 * self.unit))
        images = {key: textlib.label(name, size, "medium", (190, 200, 220), shadow=2)
                  for key, name, *_ in PLANETS}
        when = time.strftime("%d %b %Y", time.localtime(self.start_date))
        note = (f"Illustrative · not to scale · motion sped up · planets started at their "
                f"approximate positions on {when}" if self.real_start else
                "Illustrative · not to scale · positions are arbitrary")
        images["_note"] = textlib.label(note, max(11, int(15 * self.unit)), "regular",
                                        (150, 160, 180), shadow=2)
        return images

    def _layout(self, w: float, h: float) -> None:
        self.cx, self.cy = w * 0.5, h * 0.52
        self.rx = min(w * 0.47, h * 0.45 / SQUASH)
        self.ry = self.rx * SQUASH

    def _orbits_image(self) -> np.ndarray:
        w, h = int(self.width), int(self.height)
        scale = 2
        image = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for _key, _name, au, _p, _s, _c in PLANETS:
            f = orbit_fraction(au)
            rx, ry = self.rx * f * scale, self.ry * f * scale
            cx, cy = self.cx * scale, self.cy * scale
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(120, 140, 190, 70),
                         width=max(2, int(1.6 * scale * max(1.0, self.unit))))
        image = image.resize((w, h), Image.LANCZOS)
        return np.asarray(image, np.uint8).copy()

    def setup(self, canvas) -> None:
        self.surface = {k: self.upload(canvas, px, BLEND, k) for k, px in self.surface_px.items()}
        self.shade = self.upload(canvas, self.shade_px, MOD, "shade")
        self.ring_tex = self.upload(canvas, self.rings_px, BLEND, "rings")
        self.sun = self.upload(canvas, self.sun_px, BLEND, "sun")
        self.orbit_tex = self.upload(canvas, self.orbit_px, BLEND, "orbits") \
            if self.orbit_px is not None else None
        self.labels = {k: self.upload(canvas, px, BLEND, f"label.{k}")
                       for k, px in self._label_images().items()}
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["glow"], ADD, "glow")
        self.corona_tex = self.upload(canvas, self.sprites["corona"], ADD, "corona")
        self.surface_px = self.shade_px = self.rings_px = self.sun_px = None
        self.orbit_px = self.sprites = None

    def resize(self, width: int, height: int) -> bool:
        changed = (int(width), int(height)) != (int(self.width), int(self.height))
        super().resize(width, height)
        self._layout(width, height)
        return changed and (self.setting("orbits", True) or self.setting("planet_labels", False))

    def settings_changed(self, keys: set) -> bool:
        return bool(keys & {"orbits", "planet_labels"})

    def position(self, key: str, au: float, period: float, t: float) -> tuple:
        angle = self.start[key] + angular_speed(period) * t
        f = orbit_fraction(au)
        x = self.cx + math.cos(angle) * self.rx * f
        y = self.cy - math.sin(angle) * self.ry * f
        return x, y, angle

    def draw(self, canvas) -> None:
        w, h, t, u = self.width, self.height, self.t, self.unit
        canvas.clear((2, 2, 7))
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, alpha=0.8)
        if self.orbit_tex is not None:
            canvas.image(self.orbit_tex, 0, 0, w, h)
        self._draw_belt(canvas, t)
        bodies = [(self.position(key, au, period, t), key, size) for key, _n, au, period, size, _c
                  in PLANETS]
        behind = [b for b in bodies if b[0][1] < self.cy]
        front = [b for b in bodies if b[0][1] >= self.cy]
        for body in sorted(behind, key=lambda b: b[0][1]):
            self._draw_planet(canvas, *body)
        self._draw_sun(canvas, t)
        for body in sorted(front, key=lambda b: b[0][1]):
            self._draw_planet(canvas, *body)
        if self.labels:
            for (x, y, _a), key, size in bodies:
                tex = self.labels.get(key)
                if tex is not None:
                    canvas.image(tex, x + size * u * 0.8, y - tex.height - size * u * 0.4, alpha=210)
            note = self.labels.get("_note")
            if note is not None:
                canvas.image(note, w - note.width - h * 0.03, h - note.height - h * 0.025, alpha=200)

    def _draw_sun(self, canvas, t: float) -> None:
        u = self.unit
        pulse = 1.0 + 0.03 * math.sin(t * 0.7) + 0.02 * math.sin(t * 1.9)
        canvas.centered(self.corona_tex, self.cx, self.cy, 520 * u * pulse, 520 * u * pulse,
                        color=(255, 150, 60), alpha=60)
        canvas.centered(self.glow_tex, self.cx, self.cy, 230 * u * pulse, 230 * u * pulse,
                        color=(255, 196, 110), alpha=170)
        canvas.centered(self.sun, self.cx, self.cy, 54 * u, 54 * u, color=(255, 236, 196))

    def _draw_planet(self, canvas, position, key, size) -> None:
        x, y, _angle = position
        u = self.unit
        d = max(4.0, size * u * 1.15)
        toward_sun = math.degrees(math.atan2(self.cy - y, self.cx - x))
        if key == "saturn":
            rw = d * 2.6
            rh = rw
            half = self.ring_tex.height // 2
            canvas.image(self.ring_tex, x - rw / 2, y - rh / 2, rw, rh / 2,
                         src=(0, 0, self.ring_tex.width, half))
        canvas.centered(self.surface[key], x, y, d, d)
        canvas.centered(self.shade, x, y, d, d, angle=toward_sun)
        if key == "saturn":
            canvas.image(self.ring_tex, x - rw / 2, y, rw, rh / 2,
                         src=(0, half, self.ring_tex.width, self.ring_tex.height - half))
        if key == "earth":
            moon_angle = self.t * 2 * math.pi / 5.0
            mx = x + math.cos(moon_angle) * d * 1.3
            my = y - math.sin(moon_angle) * d * 1.3 * SQUASH * 1.6
            canvas.centered(self.surface["mercury"], mx, my, d * 0.3, d * 0.3, color=(200, 200, 200))

    def _draw_belt(self, canvas, t: float) -> None:
        omega = 2 * math.pi / (EARTH_YEAR_SECONDS * (self.belt_r / orbit_fraction(1.0)) ** 1.2 * 4)
        a = self.belt_a + omega * np.float32(t)
        x = self.cx + np.cos(a) * self.belt_r * np.float32(self.rx)
        y = self.cy - np.sin(a) * self.belt_r * np.float32(self.ry)
        size = np.float32(2.2 * self.unit + 0.5)
        self.belt_batch.sprites(x, y, size, size, (170, 160, 150), self.belt_b * 120)
        self.belt_batch.draw(canvas, self.star_tex, ADD)
