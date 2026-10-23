"""Scene A — Galaxy. Two views, chosen by the ``galaxy_view`` setting:

- ``inside`` (the default): the Milky Way across the sky, seen from within
  the disk (``milkyway.InsideGalaxy``);
- ``outside``: a spiral galaxy turning slowly, seen at an angle
  (``OutsideGalaxy``, below).

Outside view: the disk is generated face-on (logarithmic spiral arms, a warm bulge, dust
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
from .parts import FadingStars, Grain, common_sprites, density_count, sky_gradient

INCLINATION = math.radians(63.0)     # 0 = face-on
TILT = -21.0                         # degrees, on screen
TURN_SECONDS = 1500.0                # one turn of the arm pattern at speed 1
COMPOSE_STEP = 1.0                   # software renderer: degrees between cached composites
GENTLE_TWINKLE = 0.35                # gentle motion: disk stars twinkle this much slower


def _bilinear():
    from PIL import Image
    return getattr(Image, "Resampling", Image).BILINEAR


def _add_centered(out: np.ndarray, layer: np.ndarray) -> None:
    """Add ``layer`` (H, W, 3) into ``out`` with their centres together (clipped)."""
    oh, ow = out.shape[:2]
    lh, lw = layer.shape[:2]
    x0, y0 = (ow - lw) // 2, (oh - lh) // 2
    ox0, oy0 = max(0, x0), max(0, y0)
    ox1, oy1 = min(ow, x0 + lw), min(oh, y0 + lh)
    if ox1 > ox0 and oy1 > oy0:
        out[oy0:oy1, ox0:ox1] += layer[oy0 - y0:oy1 - y0, ox0 - x0:ox1 - x0]


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
    """The catalogue's Galaxy scene: ``create`` returns the view the settings ask for."""

    id = "galaxy"

    @classmethod
    def create(cls, ctx):
        if ctx.setting("galaxy_view", "inside") == "outside":
            return OutsideGalaxy(ctx)
        from .milkyway import InsideGalaxy
        return InsideGalaxy(ctx)


class OutsideGalaxy(Scene):
    id = "galaxy"
    STARS = 1100
    DISK_STARS = 260

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        self.diameter_factor = 1.5
        size = ctx.texture_size(1400, minimum=256)
        if self.software:          # composed 1:1 on the CPU: as large as it is drawn
            size = max(size, int(min(w, h) * self.diameter_factor))
        size = min(size, int(min(w, h) * self.diameter_factor * 1.15), ctx.max_texture)
        self.disk_size = max(256, size)
        rng = ctx.rng("galaxy")
        self.disk_px = galaxy_disk(rng, self.disk_size, q.detail)
        sky = 1.0 if self.software else min(1.0, q.texture + 0.25)    # software: drawn 1:1
        gw, gh = max(64, int(w * sky)), max(64, int(h * sky))
        self.back_px = sky_gradient(ctx.rng("space"), gw, gh,
                                    [(0.0, (3, 3, 10)), (0.5, (6, 5, 16)), (1.0, (3, 4, 11))],
                                    dither=1.0)
        self.tiny_px = [tiny_galaxy(ctx.rng(f"tiny{i}")) for i in range(3)]
        trng = ctx.rng("tiny-pos")
        self.tiny = [(trng.uniform(0.03, 0.97), trng.uniform(0.04, 0.96), trng.uniform(0.012, 0.03),
                      trng.uniform(0, 360), int(trng.integers(3)), trng.uniform(0.35, 0.7))
                     for _ in range(9)]
        capacity, _ = density_count(self.STARS, q, 2.0)
        # The distant stars never move: each fades in and out where it is.
        self.stars = FadingStars(ctx.rng("stars"), capacity, size=(1.3, 5.5), saturation=0.5)
        if self.gentle:
            self.stars.calm()
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
        self.composite_px = {}
        if self.software:
            self._prepare_composing()
            self.composite_px = {0: self.compose(0), 1: self.compose(1)}

    def setup(self, canvas) -> None:
        self.composite_tex = {}                      # software: step -> texture
        self.composing = {}                          # software: step -> Future
        for step, pixels in self.composite_px.items():
            self.composite_tex[step] = self.upload(canvas, pixels, ADD, f"composite{step}")
        self.composite_px = {}
        self.disk = self.upload(canvas, self.disk_px, NONE, "disk")
        self.frame = canvas.target(self.disk_size, self.disk_size, "galaxy.frame", ADD)
        self.textures.append(self.frame)
        self.back = self.upload(canvas, self.back_px, NONE, "space")
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
                            size, 0.0 if self.software else angle, alpha=int(255 * a))
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, alpha=0.9)
        cx, cy = w * 0.5 + sway_x, h * 0.5 + sway_y
        diameter = min(w, h) * self.diameter_factor
        if w < h:                                   # portrait: keep the long axis on screen
            diameter = w * 1.15
        squash = math.cos(INCLINATION)
        angle = (t / TURN_SECONDS) * 360.0
        breathing = 0.93 + 0.07 * math.sin(t / 23.0) + 0.03 * math.sin(t / 7.3)
        tint = (255, int(244 + 8 * math.sin(t / 61.0)), 255)
        glow = float(self.setting("nebula_intensity", 1.0))
        level = min(255, int(255 * (0.35 + 0.65 * glow) * breathing))
        if self.ctx.accelerated:
            # Turn the disk in its own plane, then draw it foreshortened and tilted.
            self._turn_disk(canvas, angle)
            canvas.centered(self.frame, cx, cy, diameter, diameter * squash, TILT,
                            color=tint, alpha=level)
            self._draw_glows(canvas, cx, cy, diameter, squash, breathing, glow)
        else:
            self._draw_composite(canvas, cx, cy, angle, tint, level)
        self._draw_disk_stars(canvas, cx, cy, diameter, squash, angle)

    def _turn_disk(self, canvas, angle: float) -> None:
        s = self.disk_size
        with canvas.into(self.frame):
            canvas.clear((0, 0, 0), alpha=0)
            canvas.image(self.disk, 0, 0, s, s, angle=angle)

    def _draw_glows(self, canvas, cx, cy, diameter, squash, breathing, glow) -> None:
        core = diameter * 0.42
        canvas.centered(self.core_tex, cx, cy, core, core * (0.55 + 0.45 * squash), TILT,
                        color=(255, 222, 176), alpha=int(110 * breathing))
        canvas.centered(self.soft_tex, cx, cy, diameter * 0.95, diameter * 0.95 * squash, TILT,
                        color=(120, 130, 200), alpha=int(36 * (0.4 + 0.6 * glow)))

    def resize(self, width: int, height: int) -> bool:
        super().resize(width, height)
        return self.software          # the composed images are made for one size

    def settings_changed(self, keys: set) -> bool:
        return "galaxy_view" in keys

    def close(self) -> None:
        for future in getattr(self, "composing", {}).values():
            future.cancel()
        super().close()

    def _draw_composite(self, canvas, cx, cy, angle, tint, level) -> None:
        """Software renderer: turning and tilting big images costs tens of milliseconds a
        frame, so the tilted galaxy comes from images composed at whole steps of
        COMPOSE_STEP degrees, and each frame blends the two steps either side of the true
        angle: it turns without visible steps. The next step is composed off the render
        thread while the current two are shown."""
        step = math.floor(angle / COMPOSE_STEP)
        here = self._composite(canvas, step)
        there = self._composite(canvas, step + 1)
        for old in [k for k in self.composite_tex if k not in (step, step + 1)]:
            texture = self.composite_tex.pop(old)
            texture.destroy()
            self.textures.remove(texture)
        for old in [k for k in self.composing if k <= step]:
            self.composing.pop(old).cancel()
        if self.ctx.background is not None and step + 2 not in self.composing:
            self.composing[step + 2] = self.ctx.background(self.compose, step + 2)
        f = min(1.0, max(0.0, angle / COMPOSE_STEP - step))
        scale = level / 255.0
        for texture, weight in ((here, 1.0 - f), (there, f)):
            if weight > 0.004:
                canvas.centered(texture, cx, cy, texture.width, texture.height,
                                color=tuple(int(c * scale * weight + 0.5) for c in tint))
        self.grain.draw(canvas)

    def _composite(self, canvas, step: int):
        texture = self.composite_tex.get(step)
        if texture is not None:
            return texture
        future = self.composing.pop(step, None)
        if future is not None and future.done() and not future.cancelled() \
                and future.exception() is None:
            pixels = future.result()
        else:                       # not ready (the worker may be preparing a scene): now
            if future is not None:
                future.cancel()
            pixels = self.compose(step)
        texture = self.upload(canvas, pixels, ADD, f"composite{step}")
        self.composite_tex[step] = texture
        return texture

    # -- the tilted galaxy composed on the CPU (software renderer) --------------
    def geometry(self) -> tuple:
        """(diameter, squash, (width, height) of the tilted galaxy's bounding box)."""
        w, h = self.width, self.height
        diameter = w * 1.15 if w < h else min(w, h) * self.diameter_factor
        squash = math.cos(INCLINATION)
        a, b = diameter / 2.0, diameter * squash / 2.0
        t = math.radians(TILT)
        half_w = math.sqrt((a * math.cos(t)) ** 2 + (b * math.sin(t)) ** 2) + 2
        half_h = math.sqrt((a * math.sin(t)) ** 2 + (b * math.cos(t)) ** 2) + 2
        return diameter, squash, (int(2 * half_w), int(2 * half_h))

    def _prepare_composing(self) -> None:
        """What compose() needs: the disk with its alpha multiplied in (an additive
        layer) and the glows, which do not turn, added once into a base image."""
        from PIL import Image
        bilinear = _bilinear()
        disk = self.disk_px.astype(np.float32)
        premultiplied = disk[..., :3] * (disk[..., 3:4] / 255.0)
        self.disk_premultiplied = Image.fromarray(
            np.clip(premultiplied + 0.5, 0, 255).astype(np.uint8), "RGB")
        diameter, squash, (cw, ch) = self.geometry()
        base = np.zeros((ch, cw, 3), np.float32)
        core = diameter * 0.42
        for sprite, w, h, color, alpha in (
                (self.sprites["core"], core, core * (0.55 + 0.45 * squash), (255, 222, 176), 110),
                (self.sprites["soft"], diameter * 0.95, diameter * 0.95 * squash,
                 (120, 130, 200), 36)):
            shape = Image.fromarray(sprite[..., 3], "L").resize(
                (max(1, round(w)), max(1, round(h))), bilinear).rotate(-TILT, bilinear, expand=True)
            weight = np.asarray(shape, np.float32) * (alpha / (255.0 * 255.0))
            _add_centered(base, weight[..., None] * np.asarray(color, np.float32))
        self.composite_base = base

    def compose(self, step: int) -> np.ndarray:
        """The tilted galaxy at ``step`` x COMPOSE_STEP degrees as an opaque RGBA image to
        draw additively: the picture the GPU path draws each frame (turned in its plane,
        foreshortened, tilted, with the glows). Thread-safe: reads only prepared data."""
        bilinear = _bilinear()
        diameter, squash, _size = self.geometry()
        disk = self.disk_premultiplied.rotate(-step * COMPOSE_STEP, bilinear)
        disk = disk.resize((max(1, round(diameter)), max(1, round(diameter * squash))), bilinear)
        disk = disk.rotate(-TILT, bilinear, expand=True)
        out = self.composite_base.copy()
        _add_centered(out, np.asarray(disk, np.float32))
        image = np.empty(out.shape[:2] + (4,), np.uint8)
        image[..., :3] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
        image[..., 3] = 255                  # opaque: drawn with ADD, black adds nothing
        return image

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
        rate = (0.6 + self.orbit_b) * (GENTLE_TWINKLE if self.gentle else 1.0)
        twinkle = 0.85 + 0.15 * np.sin(np.float32(t) * rate + self.orbit_a * 7.0)
        alpha = 255.0 * self.orbit_b * twinkle * np.clip((self.orbit_r - 0.1) / 0.1, 0, 1)
        self.orbit_batch.sprites(px, py, size, size, self.orbit_c, alpha)
        self.orbit_batch.draw(canvas, self.star_tex, ADD, n)
