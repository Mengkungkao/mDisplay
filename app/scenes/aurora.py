"""Scene D — Aurora: curtains of green and cyan light over dark mountains.

Each curtain is a triangle mesh with per-vertex colour: a bright green lower
edge fading up through cyan to a faint violet top. Its base line, height
and brightness come from several slow waves and evolving noise, so the
motion never repeats mechanically; fine vertical rays drift along it. The
overall activity rises and falls over minutes.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise, sprites
from ..gfx.batch import Mesh
from ..gfx.canvas import ADD, BLEND
from .base import Scene
from .parts import Grain, StarField, common_sprites, density_count, ridge_line, silhouette, sky_gradient

# Colour up a curtain: (height fraction, (r, g, b), alpha)
CURTAIN = ((0.0, (90, 255, 170), 0.0), (0.03, (110, 255, 175), 1.0), (0.1, (70, 255, 160), 0.8),
           (0.4, (50, 230, 180), 0.5), (0.68, (50, 150, 215), 0.2), (1.0, (130, 80, 210), 0.0))
SKY = [(0.0, (1, 2, 7)), (0.6, (2, 6, 14)), (1.0, (4, 10, 18))]


class Curtain:
    def __init__(self, rng, columns: int, base: float, height: float, speed: float,
                 strength: float, tint=(1.0, 1.0, 1.0)):
        self.rows = len(CURTAIN) - 1
        self.mesh = Mesh.strip_grid(columns, self.rows)
        self.columns = columns
        self.base = base
        self.height = height
        self.speed = speed
        self.strength = strength
        self.tint = np.asarray(tint, np.float32)
        self.shape = noise.Noise1D(rng, cells=5, octaves=3, time_cells=64)
        self.folds = noise.Noise1D(rng, cells=9, octaves=3, time_cells=64)
        self.rays = noise.Noise1D(rng, cells=70, octaves=2, time_cells=256)
        self.waves = [(rng.uniform(0.5, 1.4), rng.uniform(0.004, 0.012), rng.uniform(0, 6.3),
                       rng.uniform(0.025, 0.06)) for _ in range(3)]
        self.x = np.linspace(-0.04, 1.04, columns + 1, dtype=np.float32)
        fractions = np.array([f for f, _, _ in CURTAIN], np.float32)
        self.fraction = fractions[:, None]
        self.colors = np.array([c for _, c, _ in CURTAIN], np.float32)[:, None, :]
        self.alphas = np.array([a for _, _, a in CURTAIN], np.float32)[:, None]

    def update_mesh(self, t: float, w: float, h: float, activity: float) -> None:
        x = self.x
        s = t * self.speed
        base = np.full_like(x, self.base)
        for frequency, rate, phase, amplitude in self.waves:
            base += amplitude * np.sin(2 * math.pi * (frequency * x + rate * s) + phase)
        base += 0.07 * self.shape.at(x, s * 0.01)
        height = self.height * (0.75 + 0.45 * (self.shape.at(x + 0.37, s * 0.008) * 0.5 + 0.5))
        fold = np.clip(self.folds.at(x, s * 0.012) * 0.9 + 0.55, 0, 1) ** 1.6
        rays = 0.55 + 0.45 * np.clip(self.rays.at(x - s * 0.002, s * 0.03) * 1.3 + 0.5, 0, 1)
        brightness = np.clip(fold * rays * activity * self.strength, 0, 1.2)
        edge = np.clip(np.minimum(x + 0.04, 1.04 - x) / 0.12, 0, 1)
        brightness *= edge
        sway = 0.012 * np.sin(2 * math.pi * (x * 2.3 + s * 0.006)) * self.fraction
        px = (x[None, :] + sway) * np.float32(w)
        py = (base[None, :] - self.fraction * height[None, :]) * np.float32(h)
        v = self.mesh.vertices
        v["x"] = px.ravel()
        v["y"] = py.ravel()
        color = self.colors * self.tint
        v["r"] = np.clip(np.broadcast_to(color[..., 0], px.shape), 0, 255).astype(np.uint8).ravel()
        v["g"] = np.clip(np.broadcast_to(color[..., 1], px.shape), 0, 255).astype(np.uint8).ravel()
        v["b"] = np.clip(np.broadcast_to(color[..., 2], px.shape), 0, 255).astype(np.uint8).ravel()
        v["a"] = np.clip(self.alphas * brightness[None, :] * 255.0, 0, 255).astype(np.uint8).ravel()


class AuroraScene(Scene):
    id = "aurora"
    STARS = 700

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        tex = min(1.0, q.texture + 0.25)
        self.sky_px = sky_gradient(ctx.rng("sky"), max(64, int(w * tex)), max(64, int(h * tex)), SKY)
        self.mountain_px = None
        if self.setting("mountains", True):
            mh = max(48, int(h * 0.32))
            far = ridge_line(ctx.rng("far"), max(64, w), base=h * 0.08, amplitude=h * 0.17, cells=3,
                             octaves=6, ridged=True)
            far = 0.6 * far + 0.4 * ridge_line(ctx.rng("far2"), max(64, w), base=h * 0.07,
                                                amplitude=h * 0.1, cells=7, octaves=5)
            near = ridge_line(ctx.rng("near"), max(64, w), base=h * 0.03, amplitude=h * 0.08,
                              cells=2, octaves=6, ridged=True)
            far_img = silhouette(np.minimum(far, mh - 1), mh, (4, 8, 13), rim=(26, 56, 50),
                                 rim_width=2.0)
            near_img = silhouette(np.minimum(near, mh - 1), mh, (1, 2, 4), rim=(10, 24, 20),
                                  rim_width=1.5)
            alpha_n = near_img[..., 3:4].astype(np.float32) / 255.0
            combined = far_img.astype(np.float32)
            combined[..., :3] = combined[..., :3] * (1 - alpha_n) + near_img[..., :3] * alpha_n
            combined[..., 3:4] = np.maximum(combined[..., 3:4], near_img[..., 3:4])
            self.mountain_px = combined.astype(np.uint8)
        columns = (90, 160, 240, 320)[min(3, q.detail)]
        rng = ctx.rng("curtains")
        self.curtains = [Curtain(rng, columns, base=0.72, height=0.55, speed=1.0, strength=1.0)]
        if q.detail >= 1:
            self.curtains.insert(0, Curtain(rng, columns // 2, base=0.5, height=0.32, speed=0.6,
                                            strength=0.4, tint=(1.0, 0.82, 1.08)))
        self.activity = noise.Noise1D(ctx.rng("activity"), cells=4, octaves=2, time_cells=32)
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, region=(0, 0, 1, 0.8), size=(1.3, 5.0),
                               twinkle=0.35, twinkle_speed=(0.1, 1.0), saturation=0.4)
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.sky = self.upload(canvas, self.sky_px, BLEND, "sky")
        self.mountains = self.upload(canvas, self.mountain_px, BLEND, "mountains") \
            if self.mountain_px is not None else None
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["soft"], ADD, "soft")
        self.grain.setup(self, canvas)
        self.sky_px = self.mountain_px = self.sprites = None

    def settings_changed(self, keys: set) -> bool:
        return "mountains" in keys

    def level(self, t: float) -> float:
        """Overall activity 0.45..1.0, changing over minutes."""
        a = float(self.activity.at(np.array([0.3], np.float32), t * 0.004)[0])
        return 0.45 + 0.55 * min(1.0, max(0.0, a * 1.2 + 0.55))

    def draw(self, canvas) -> None:
        w, h, t = self.width, self.height, self.t
        canvas.image(self.sky, 0, 0, w, h)
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, offset_x=-t * 0.8 * self.unit,
                        wrap=True, alpha=0.7)
        activity = self.level(t)
        glow = int(28 * activity)
        canvas.centered(self.glow_tex, w * 0.5, h * 0.55, w * 1.6, h * 0.8, color=(40, 200, 120),
                        alpha=glow)
        for curtain in self.curtains:
            curtain.update_mesh(t, w, h, activity)
            curtain.mesh.draw(canvas, None, ADD)
        if self.mountains is not None:
            canvas.image(self.mountains, 0, h * 0.68, w, h * 0.32)
        self.grain.draw(canvas)
