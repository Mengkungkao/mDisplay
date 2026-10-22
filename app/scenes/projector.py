"""Scene H — Galaxy projector: turning nebula clouds and laser stars, like a star
projector lighting up a ceiling.

The whole sky turns about the centre of the screen. Every layer is drawn
larger than the screen's diagonal, so however far it has turned no corner or
edge of a layer ever shows; with the soft-edges setting the picture fades out
before the screen's border, as projected light does. The nebula layers turn
at slightly different rates and slowly change colour within a theme; the
laser stars are sharp points that shimmer as the dome turns.

Options (settings): colour theme, laser colour (green, red, both, off) and
turning speed. On SDL's software renderer turning large images is too slow,
so there the clouds drift instead of turning; the lasers still turn.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise, sprites
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD
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

RIM = 0.12                     # each layer fades out over the outer 12% of its radius
BREATHE = 0.03                 # and its size breathes by up to 3%
# (rate x the dome's turn, phase in the theme, size x the diagonal, strength). Every size
# keeps the fully lit part of the layer beyond the screen's corners at any angle:
# size x (1 - BREATHE) x (1 - RIM) > 1.
LAYERS = ((1.0, 0.0, 1.2, 0.9), (0.82, 0.33, 1.26, 0.75), (1.17, 0.66, 1.23, 0.6))


def nebula_disc(rng, size: int, detail: int, cells: int) -> np.ndarray:
    """A square nebula layer: wavy clouds and filaments, fading out at its rim."""
    field = noise.warped_image(rng, size, size, cells_across=cells, octaves=4 + detail, warp=2.0)
    density = noise.contrast(field, 0.44, 0.78)
    filaments = noise.fbm_image(rng, size, size, cells_across=cells * 3, octaves=3, ridged=True)
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(xx - c, yy - c) / (size / 2.0)
    rim = np.clip((1.0 - r) / RIM, 0, 1)             # nothing near the square's edges
    alpha = density * (0.65 + 0.35 * filaments) * rim
    return sprites.white(np.clip(alpha, 0, 1))


class ProjectorScene(Scene):
    id = "projector"
    LASER_COUNT = 1400

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        side = ctx.texture_size(760, minimum=192)
        rng = ctx.rng("projector")
        layers = 2 if q.detail == 0 else 3
        self.layer_px = [nebula_disc(rng, side, q.detail, cells) for cells in (3, 4, 5)[:layers]]
        n = int(self.LASER_COUNT * max(0.5, q.stars))
        lrng = ctx.rng("lasers")
        # Uniform over a disc as wide as the diagonal: turning never leaves a gap.
        self.laser_r = np.sqrt(lrng.random(n)).astype(np.float32)
        self.laser_a = lrng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.laser_b = (0.45 + 0.55 * lrng.random(n) ** 2).astype(np.float32)
        self.laser_f = lrng.uniform(0.8, 3.0, n).astype(np.float32)
        self.laser_p = lrng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.laser_pick = lrng.random(n).astype(np.float32)
        self.white_r = np.sqrt(lrng.random(n // 4)).astype(np.float32)
        self.white_a = lrng.uniform(0, 2 * math.pi, n // 4).astype(np.float32)
        self.lasers = QuadBatch(n)
        self.whites = QuadBatch(n // 4)
        self.point_px = sprites.star(32, sigma=0.13, halo=0.16)
        self.drift = [(lrng.uniform(-1, 1), lrng.uniform(-1, 1)) for _ in LAYERS]

    def setup(self, canvas) -> None:
        self.layers = [self.upload(canvas, px, ADD, f"nebula{i}") for i, px in enumerate(self.layer_px)]
        self.point = self.upload(canvas, self.point_px, ADD, "point")
        self.layer_px = self.point_px = None

    def turn(self) -> float:
        """The dome's angle in degrees."""
        speed = TURN_DEGREES_PER_SECOND.get(self.setting("projector_rotation", "slow"), 0.75)
        return self.t * speed

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
            d = diagonal * size * breathing
            if turns:
                canvas.centered(texture, cx, cy, d, d, angle * rate + phase * 120, color=tint)
            else:
                # Software renderer: drift slowly instead (rotating 2000-pixel images is too slow).
                ox = math.sin(t / 90.0 + phase * 7) * dx * diagonal * 0.012
                oy = math.cos(t / 110.0 + phase * 5) * dy * diagonal * 0.012
                canvas.centered(texture, cx + ox, cy + oy, d, d, phase * 120, color=tint)
        self._draw_points(canvas, cx, cy, diagonal, angle)

    def _draw_points(self, canvas, cx, cy, diagonal, angle) -> None:
        t = self.t
        u = self.unit
        theta = math.radians(angle)
        radius = np.float32(diagonal * 0.5)
        colors = LASERS.get(self.setting("projector_lasers", "green"), LASERS["green"])
        if colors:
            a = self.laser_a + np.float32(theta)
            x = cx + np.cos(a) * self.laser_r * radius
            y = cy + np.sin(a) * self.laser_r * radius
            shimmer = 0.62 + 0.38 * np.sin(self.laser_f * np.float32(t) + self.laser_p) ** 2
            alpha = 255.0 * self.laser_b * shimmer
            palette = np.array(colors, np.float32)
            rgb = palette[np.minimum((self.laser_pick * len(colors)).astype(int), len(colors) - 1)]
            size = np.float32(5.0 * max(u, 0.6)) * (0.8 + 0.9 * self.laser_b)
            self.lasers.sprites(x, y, size, size, rgb, alpha)
            self.lasers.draw(canvas, self.point, ADD)
        a = self.white_a + np.float32(theta)
        x = cx + np.cos(a) * self.white_r * radius
        y = cy + np.sin(a) * self.white_r * radius
        size = np.float32(4.0 * max(u, 0.6))
        self.whites.sprites(x, y, size, size, (235, 238, 255), 170)
        self.whites.draw(canvas, self.point, ADD)
