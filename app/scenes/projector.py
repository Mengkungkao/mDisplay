"""Scene H — Galaxy projector: turning nebula clouds and laser stars, like a star
projector lighting up a ceiling.

Like a real one: the clouds are soft and uneven, with fine wisps at their
edges and a little colour variation inside each; the laser stars are tiny,
sharp points of uneven brightness with a faint shimmer; and the picture
falls off towards the edges as a projector's lens does, the points there a
little larger and softer (out of focus).

The whole sky turns about the centre of the screen. Every layer is drawn
larger than the screen's diagonal, so however far it has turned no corner or
edge of a layer ever shows; with the soft-edges setting the picture fades out
before the screen's border, as projected light does. The nebula layers turn
at slightly different rates and slowly change colour within a theme; the
laser stars are sharp points that shimmer as the dome turns.

Options (settings): colour theme, laser colour (green, red, both, off) and
turning speed. On SDL's software renderer turning large images is too slow,
so there the clouds drift instead of turning (scaled once to the size they
are drawn at); the lasers still turn. Gentle motion halves the turning and
slows the shimmer.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise, sprites
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, MOD
from ..gfx.palette import Cycle
from .base import Scene

THEMES = {
    "cosmic": Cycle([(70, 40, 230), (150, 50, 225), (230, 60, 170), (60, 90, 235)]),
    "ocean": Cycle([(20, 80, 225), (20, 170, 215), (30, 205, 150), (40, 120, 235)]),
    "aurora": Cycle([(30, 225, 120), (20, 190, 175), (90, 240, 110), (30, 160, 205)]),
    "sunset": Cycle([(235, 60, 40), (240, 125, 40), (205, 50, 125), (150, 40, 170)]),
    "rainbow": Cycle([(230, 50, 60), (240, 150, 40), (60, 220, 90), (40, 170, 230),
                      (110, 60, 235), (220, 60, 190)]),
}
LASERS = {"green": [(60, 255, 90)], "red": [(255, 45, 45)],
          "both": [(60, 255, 90), (255, 45, 45)], "off": []}
TURN_DEGREES_PER_SECOND = {"off": 0.0, "slow": 0.75, "medium": 2.0, "fast": 4.8}
COLOR_SECONDS = 240.0          # one trip round the theme at speed 1
GENTLE_TURN = 0.5              # gentle motion: the dome turns at half the chosen speed
GENTLE_SHIMMER = 0.3           # and the laser stars shimmer this much slower
SHIMMER = 0.16                 # how much a laser star's brightness shimmers (0..1)
LASER_SIZE = 3.2               # a laser star's size in pixels at 1080p (before the lens)
LENS_FALLOFF = 0.42            # the lens: brightness lost at the corners (0..1)
LENS_DEFOCUS = 1.1             # the lens: points at the corners are this much larger

RIM = 0.12                     # each layer fades out over the outer 12% of its radius
BREATHE = 0.03                 # and its size breathes by up to 3%
# (rate x the dome's turn, phase in the theme, size x the diagonal, strength). Every size
# keeps the fully lit part of the layer beyond the screen's corners at any angle:
# size x (1 - BREATHE) x (1 - RIM) > 1.
LAYERS = ((1.0, 0.0, 1.2, 0.9), (0.82, 0.33, 1.26, 0.75), (1.17, 0.66, 1.23, 0.6))


def nebula_disc(rng, size: int, detail: int, cells: int) -> np.ndarray:
    """A square nebula layer: soft, uneven clouds with fine wisps at their edges and a
    little colour variation (cooler and warmer parts once tinted), fading out at its rim."""
    octaves = 4 + detail
    # Smooth fields are made at a quarter or a third of the size and scaled up (seamless):
    # the noise costs per pixel, the scaling very little.
    quarter, third = max(16, size // 4), max(16, size // 3)

    def big(field):
        return noise.upsample(field, size, size)
    field = big(noise.warped_image(rng, quarter, quarter, cells_across=cells, octaves=octaves,
                                   warp=2.2))
    low, high = rng.uniform(0.4, 0.5), rng.uniform(0.74, 0.84)       # each layer its own
    density = noise.contrast(field, low, high)
    # Large empty patches between the clouds, so the layer is not a uniform veil.
    patchy = noise.contrast(big(noise.fbm_image(rng, quarter, quarter, cells_across=cells * 2,
                                                octaves=3)), 0.34, 0.72)
    # Wisps: thin warped ridges at the clouds' edges, hardly any inside or away from them.
    wisps = big(noise.warped_image(rng, third, third, cells_across=cells * 5, octaves=3, warp=0.7))
    wisps = noise.contrast(1.0 - np.abs(wisps * 2.0 - 1.0), 0.78, 0.97)
    edges = np.clip(density * (1.0 - density) * 4.0, 0, 1)
    fine = big(noise.fbm_image(rng, third, third, cells_across=cells * 8, octaves=2))
    alpha = 1.25 * density * (0.3 + 0.7 * patchy) * (0.7 + 0.3 * fine) \
        + 0.4 * wisps * edges * (0.3 + 0.7 * patchy)
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(xx - c, yy - c) / (size / 2.0)
    rim = np.clip((1.0 - r) / RIM, 0, 1)             # nothing near the square's edges
    alpha = np.clip(alpha * rim, 0, 1)
    hue = big(noise.fbm_image(rng, quarter, quarter, cells_across=cells, octaves=2))
    rgb = np.empty((size, size, 3), np.float32)
    rgb[..., 0] = 1.0 - 0.32 * hue                   # warmer here, cooler there
    rgb[..., 1] = 0.92 + 0.08 * np.abs(hue - 0.5) * 2.0
    rgb[..., 2] = 0.68 + 0.32 * hue
    return sprites.rgba(rgb, alpha)


def lens(width: int, height: int) -> np.ndarray:
    """A multiply layer: the projector lens's fall-off, white in the middle."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    r2 = ((x + 0.5 - width / 2.0) ** 2 + (y + 0.5 - height / 2.0) ** 2) / (
        (width / 2.0) ** 2 + (height / 2.0) ** 2)
    value = 1.0 - LENS_FALLOFF * r2 ** 1.2
    image = np.empty((height, width, 4), np.uint8)
    image[..., :3] = np.clip(value * 255.0 + 0.5, 0, 255).astype(np.uint8)[..., None]
    image[..., 3] = 255
    return image


class ProjectorScene(Scene):
    id = "projector"
    LASER_COUNT = 1400

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        side = ctx.texture_size(760, minimum=192)
        rng = ctx.rng("projector")
        layers = 2 if q.detail == 0 else 3
        diagonal = math.hypot(self.width, self.height)
        self.layer_px = []
        for cells, layer in zip((3, 4, 5)[:layers], LAYERS):
            self.checkpoint()
            # Software: drawn 1:1 at a fixed size (no breathing), so made at that size and
            # the wisps stay sharp.
            size = max(side, int(diagonal * layer[2])) if self.software else side
            self.layer_px.append(nebula_disc(rng, size, q.detail, cells))
        lens_size = (self.width, self.height) if self.software else (256, 144)
        self.lens_px = lens(max(8, int(lens_size[0])), max(8, int(lens_size[1])))
        n = int(self.LASER_COUNT * max(0.5, q.stars))
        lrng = ctx.rng("lasers")
        # Uniform over a disc as wide as the diagonal: turning never leaves a gap.
        self.laser_r = np.sqrt(lrng.random(n)).astype(np.float32)
        self.laser_a = lrng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.laser_b = (0.4 + 0.6 * lrng.random(n) ** 2).astype(np.float32)   # uneven
        self.laser_f = lrng.uniform(0.8, 3.0, n).astype(np.float32)
        self.laser_p = lrng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.laser_pick = lrng.random(n).astype(np.float32)
        self.white_r = np.sqrt(lrng.random(n // 4)).astype(np.float32)
        self.white_a = lrng.uniform(0, 2 * math.pi, n // 4).astype(np.float32)
        self.lasers = QuadBatch(n)
        self.whites = QuadBatch(n // 4)
        self.point_px = sprites.star(16, sigma=0.3, halo=0.0)             # fills its small quad
        self.drift = [(lrng.uniform(-1, 1), lrng.uniform(-1, 1)) for _ in LAYERS]

    def setup(self, canvas) -> None:
        self.layers = [self.upload(canvas, px, ADD, f"nebula{i}") for i, px in enumerate(self.layer_px)]
        self.point = self.upload(canvas, self.point_px, ADD, "point")
        self.lens = self.upload(canvas, self.lens_px, MOD, "lens")
        self.layer_px = self.point_px = self.lens_px = None

    def turn(self) -> float:
        """The dome's angle in degrees."""
        speed = TURN_DEGREES_PER_SECOND.get(self.setting("projector_rotation", "slow"), 0.75)
        return self.t * speed * (GENTLE_TURN if self.gentle else 1.0)

    def draw(self, canvas) -> None:
        w, h, t = self.width, self.height, self.t
        canvas.clear((0, 0, 0))
        cx, cy = w / 2.0, h / 2.0
        diagonal = math.hypot(w, h)
        angle = self.turn()
        theme = THEMES.get(self.setting("projector_colors", "cosmic"), THEMES["cosmic"])
        intensity = min(1.4, float(self.setting("nebula_intensity", 1.0)))
        turns = self.ctx.accelerated
        for texture, (rate, phase, size, strength), (dx, dy) in zip(self.layers, LAYERS, self.drift):
            color = theme.at(t / COLOR_SECONDS + phase)
            breathing = 1.0 + BREATHE * math.sin(t / 17.0 + phase * 9)
            level = strength * intensity * (0.88 + 0.12 * math.sin(t / 29.0 + phase * 5))
            tint = tuple(min(255, int(c * level)) for c in color)
            d = texture.width if self.software else diagonal * size * breathing
            if turns:
                canvas.centered(texture, cx, cy, d, d, angle * rate + phase * 120, color=tint)
            else:
                # Software renderer: drift slowly instead (rotating 2000-pixel images is too slow).
                ox = math.sin(t / 90.0 + phase * 7) * dx * diagonal * 0.012
                oy = math.cos(t / 110.0 + phase * 5) * dy * diagonal * 0.012
                canvas.centered(texture, cx + ox, cy + oy, d, d, color=tint)
        self._draw_points(canvas, cx, cy, diagonal, angle)

    def _draw_points(self, canvas, cx, cy, diagonal, angle) -> None:
        t = self.t
        u = max(self.unit, 0.5)
        theta = math.radians(angle)
        radius = np.float32(diagonal * 0.5)
        colors = LASERS.get(self.setting("projector_lasers", "green"), LASERS["green"])
        if colors:
            a = self.laser_a + np.float32(theta)
            x = cx + np.cos(a) * self.laser_r * radius
            y = cy + np.sin(a) * self.laser_r * radius
            rate = np.float32(t * (GENTLE_SHIMMER if self.gentle else 1.0))
            shimmer = (1.0 - SHIMMER) + SHIMMER * np.sin(self.laser_f * rate + self.laser_p) ** 2
            defocus = self.defocus(self.laser_r)
            alpha = 255.0 * self.laser_b * shimmer / np.sqrt(defocus)
            palette = np.array(colors, np.float32)
            rgb = palette[np.minimum((self.laser_pick * len(colors)).astype(int), len(colors) - 1)]
            half = np.float32(LASER_SIZE * 0.75 * u) * (0.75 + 0.5 * self.laser_b) * defocus
            self.lasers.sprites(x, y, half, half, rgb, alpha)
            self.lasers.draw(canvas, self.point, ADD)
        a = self.white_a + np.float32(theta)
        x = cx + np.cos(a) * self.white_r * radius
        y = cy + np.sin(a) * self.white_r * radius
        defocus = self.defocus(self.white_r)
        half = np.float32(LASER_SIZE * 0.6 * u) * defocus
        self.whites.sprites(x, y, half, half, (235, 238, 255), 160.0 / np.sqrt(defocus))
        self.whites.draw(canvas, self.point, ADD)
        canvas.image(self.lens, 0, 0, self.width, self.height)

    @staticmethod
    def defocus(r: np.ndarray) -> np.ndarray:
        """How much larger (softer) a point at ``r`` (0 centre .. 1 corner) is drawn."""
        return np.float32(1.0) + np.float32(LENS_DEFOCUS) * r * r
