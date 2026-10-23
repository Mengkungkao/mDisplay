"""Scene — Starlight: a clear, dark sky where stars slowly fade in and out.

Nothing moves. Each star brightens, shines a while and fades away on its own
slow cycle, then rests dark and comes back somewhere else, so the sky keeps
changing without anything travelling across it. The brightest carry a soft
halo. Fades look the same at 10 or 60 frames a second, so this scene is as
smooth on a small board's software renderer as on a GPU.
"""

from __future__ import annotations

import numpy as np

from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, NONE
from ..gfx.palette import star_colors
from .base import Scene
from .parts import FADE_CYCLE as CYCLE_SECONDS, FADE_LIT as LIT, FADE_RAMP as FADE  # noqa: F401
from .parts import common_sprites, density_count, fade_envelope as envelope, scatter, sky_gradient

SKY = [(0.0, (1, 2, 6)), (0.6, (2, 3, 9)), (1.0, (3, 5, 12))]
HALO_SHARE = 0.04              # the brightest stars that carry a halo


class StarlightScene(Scene):
    id = "starlight"
    max_fps = 24               # nothing moves: more frames would only cost power
    STARS = 1500

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        sky = 1.0 if self.software else min(1.0, q.texture + 0.25)   # software: drawn 1:1
        self.sky_px = sky_gradient(ctx.rng("sky"), max(64, int(w * sky)), max(64, int(h * sky)),
                                   SKY)
        rng = ctx.rng("starlight")
        n, _ = density_count(self.STARS, q, 2.0)
        self.period = rng.uniform(*CYCLE_SECONDS, n)
        self.phase = rng.random(n)
        self.seed_x = rng.random(n) * 100.0
        self.seed_y = rng.random(n) * 100.0
        self.peak = (rng.random(n) ** 2.4).astype(np.float32)        # most stars faint
        self.colors = star_colors(rng, n, 0.4, 0.5)
        self.halo = self.peak >= np.quantile(self.peak, 1.0 - HALO_SHARE)
        self.batch = QuadBatch(n)
        self.halos = QuadBatch(max(1, int(self.halo.sum())))
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.sky = self.upload(canvas, self.sky_px, NONE, "sky")
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["glow"], ADD, "glow")
        self.sky_px = self.sprites = None

    def stars(self, t: float, count: int) -> tuple:
        """(x 0..1, y 0..1, brightness 0..1) of the first ``count`` stars at time ``t``."""
        cycles = t / self.period[:count] + self.phase[:count]
        index = np.floor(cycles)
        level = envelope(cycles - index)
        x = scatter(index, self.seed_x[:count])
        y = scatter(index + 0.5, self.seed_y[:count])
        return x, y, level

    def draw(self, canvas) -> None:
        w, h, u = self.width, self.height, self.unit
        canvas.image(self.sky, 0, 0, w, h)
        _, count = density_count(self.STARS, self.ctx.quality,
                                 float(self.setting("star_density", 1.0)))
        x, y, level = self.stars(self.t, count)
        lit = level > 0.002
        if not lit.any():
            return
        peak = self.peak[:count][lit]
        px = (x[lit] * w).astype(np.float32)
        py = (y[lit] * h).astype(np.float32)
        alpha = ((40.0 + 215.0 * peak ** 0.6) * level[lit]).astype(np.float32)
        size = np.maximum(np.float32(1.6), np.float32(u) * (1.3 + 4.2 * peak ** 1.35))
        self.batch.sprites(px, py, size * 0.5, size * 0.5, self.colors[:count][lit], alpha)
        self.batch.draw(canvas, self.star_tex, ADD)
        halo = self.halo[:count][lit]
        if halo.any():
            glow = np.float32(max(6.0, 22.0 * u))
            self.halos.sprites(px[halo], py[halo], glow, glow, self.colors[:count][lit][halo],
                               alpha[halo] * np.float32(0.3))
            self.halos.draw(canvas, self.glow_tex, ADD)
