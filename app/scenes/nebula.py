"""Scene C — Nebula: layered clouds of glowing gas drifting at different depths.

Each gas layer is a seamless domain-warped noise field (organic, filamentary)
tinted by a slow colour cycle (blue, cyan, violet, pink, red) with its own
phase, so the layers never share a hue. A dark dust layer drifts in front,
the far stars barely move, and a few bright young stars glow inside.
Colour changes take minutes; nothing flashes.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise, sprites
from ..gfx.canvas import ADD, MOD
from ..gfx.palette import NEBULA
from .base import Scene
from .parts import Grain, StarField, common_sprites, density_count

CYCLE_SECONDS = 420.0      # one trip round the colour cycle at speed 1


def gas_layer(rng, width: int, height: int, octaves: int, low: float, high: float,
              cells: int = 3, warp: float = 1.7) -> np.ndarray:
    field = noise.warped_image(rng, width, height, cells_across=cells, octaves=octaves, warp=warp)
    density = noise.contrast(field, low, high)
    filaments = noise.fbm_image(rng, width, height, cells_across=cells * 4, octaves=3, ridged=True)
    alpha = density * (0.7 + 0.3 * filaments)
    return sprites.white(np.clip(alpha, 0, 1))


def dust_layer(rng, width: int, height: int, octaves: int) -> np.ndarray:
    """Multiply layer: white leaves the colour, darker greys dim it."""
    field = noise.warped_image(rng, width, height, cells_across=2, octaves=octaves, warp=1.2)
    dust = noise.contrast(field, 0.52, 0.75)
    shade = 1.0 - 0.75 * dust
    image = np.empty((height, width, 4), np.uint8)
    image[..., :3] = np.clip(shade * 255.0 + 0.5, 0, 255).astype(np.uint8)[..., None]
    image[..., 3] = 255
    return image


class NebulaScene(Scene):
    id = "nebula"
    STARS = 900

    LAYERS = (
        # (cells, low, high, tile size x width, drift x, drift y, phase, strength)
        (2, 0.42, 0.78, 1.9, -3.0, -1.2, 0.00, 0.85),
        (3, 0.46, 0.80, 1.5, 4.5, 1.6, 0.31, 0.75),
        (4, 0.50, 0.82, 1.25, -6.5, 2.4, 0.62, 0.6),
        (5, 0.52, 0.84, 1.1, 8.0, -3.0, 0.85, 0.45),
    )

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        layers = 2 + min(2, q.detail) if q.detail < 3 else 4
        side = ctx.texture_size(900, minimum=192)
        tw, th = side, max(96, int(side * 0.62))
        rng = ctx.rng("nebula")
        self.layer_px = [gas_layer(rng, tw, th, 4 + q.detail, low, high, cells)
                         for cells, low, high, *_ in self.LAYERS[:layers]]
        self.dust_px = dust_layer(ctx.rng("dust"), tw, th, 4 + q.detail)
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, size=(1.3, 5.0), twinkle=0.2,
                               twinkle_speed=(0.05, 0.5), saturation=0.45)
        brng = ctx.rng("bright")
        self.bright = [(brng.uniform(0.1, 0.9), brng.uniform(0.15, 0.85), brng.uniform(0.6, 1.0),
                        brng.uniform(0, 2 * math.pi)) for _ in range(7)]
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.layers = [self.upload(canvas, px, ADD, f"gas{i}") for i, px in enumerate(self.layer_px)]
        self.dust = self.upload(canvas, self.dust_px, MOD, "dust")
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.spike_tex = self.upload(canvas, self.sprites["spike"], ADD, "spike")
        self.glow_tex = self.upload(canvas, self.sprites["soft"], ADD, "soft")
        self.grain.setup(self, canvas)
        self.layer_px = self.dust_px = self.sprites = None

    def draw(self, canvas) -> None:
        w, h, t, u = self.width, self.height, self.t, self.unit
        canvas.clear((1, 1, 4))
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, offset_x=-t * 0.6 * u,
                        wrap=True, alpha=0.85)
        intensity = float(self.setting("nebula_intensity", 1.0))
        breathing = 0.9 + 0.1 * math.sin(t / 37.0)
        span = max(w, h * 16 / 9)
        for texture, (cells, _lo, _hi, size, dx, dy, phase, strength) in zip(self.layers,
                                                                             self.LAYERS):
            color = NEBULA.at(t / CYCLE_SECONDS + phase)
            level = strength * intensity * breathing
            tint = tuple(min(255, int(c * level)) for c in color)
            tile_w = span * size * (1.0 + 0.04 * math.sin(t / (60.0 + 13 * cells) + phase * 6))
            tile_h = tile_w * texture.height / texture.width
            canvas.tiled(texture, t * dx * u, t * dy * u, tile_w, tile_h, color=tint)
        dust_w = span * 1.6
        canvas.tiled(self.dust, t * 2.0 * u + w * 0.3, -t * 1.1 * u, dust_w,
                     dust_w * self.dust.height / self.dust.width)
        for x, y, b, p in self.bright:
            px, py = x * w - t * 1.4 * u, y * h
            px %= w
            color = NEBULA.at(t / CYCLE_SECONDS + p / 6.0)
            glow = 0.5 + 0.5 * b
            halo = (210 + 45 * b) * u
            canvas.centered(self.glow_tex, px, py, halo, halo,
                            color=tuple(int(c) for c in color),
                            alpha=int(70 * glow * min(1.0, intensity + 0.2)))
            star = (34 + 30 * b) * u * (0.96 + 0.04 * math.sin(t * (0.7 + b) + p))
            canvas.centered(self.spike_tex, px, py, star, star, color=(245, 246, 255),
                            alpha=int(230 * glow))
        self.grain.draw(canvas)
