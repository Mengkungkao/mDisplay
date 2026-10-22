"""Scene F — Meteor shower: meteors streaking away from one radiant.

Meteors appear anywhere in the sky but always point away from the radiant,
and those near it are short (they come almost towards us), as in a real
shower. The rate rises and falls in slow bursts; a few meteors at once at
most, a minimum gap between them, and bright fireballs are rare and leave
a faint fading train instead of a flash.
"""

from __future__ import annotations

import math

import numpy as np

from ..gfx import noise
from ..gfx.batch import QuadBatch
from ..gfx.canvas import ADD, BLEND
from .base import Scene
from .parts import (Grain, Meteors, StarField, add_trees, common_sprites, density_count,
                    ridge_line, silhouette, sky_gradient)

SKY = [(0.0, (1, 2, 8)), (0.6, (4, 8, 20)), (0.88, (10, 18, 36)), (1.0, (14, 22, 40))]
RADIANT = (0.66, 0.2)
TRAIN_SECONDS = 3.5


class MeteorShowerScene(Scene):
    id = "meteors"
    STARS = 1200

    def prepare(self) -> None:
        ctx, q = self.ctx, self.ctx.quality
        w, h = self.width, self.height
        tex = min(1.0, q.texture + 0.25)
        self.sky_px = sky_gradient(ctx.rng("sky"), max(64, int(w * tex)), max(64, int(h * tex)), SKY)
        self.horizon_px = None
        if self.setting("horizon", True):
            hh = max(32, int(h * 0.2))
            profile = ridge_line(ctx.rng("hills"), max(64, w), base=h * 0.03, amplitude=h * 0.05,
                                 cells=4)
            profile = add_trees(ctx.rng("trees"), profile, count=int(w / 40), height=h * 0.06,
                                width_px=h * 0.028, clustered=True)
            self.horizon_px = silhouette(np.minimum(profile, hh - 1), hh, (2, 3, 7), rim=(12, 16, 28))
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, region=(0, 0, 1, 0.92), size=(1.4, 5.8),
                               twinkle=0.4, twinkle_speed=(0.2, 1.4), saturation=0.5)
        self.meteors = Meteors(ctx.rng("meteors"), per_minute=18.0, max_active=5, min_gap=0.4,
                               speed=(0.35, 0.8), length=(0.08, 0.24), life=(0.6, 1.3),
                               area=(0.02, 0.02, 0.98, 0.75), radiant=RADIANT,
                               brightness=(0.4, 0.95), fireball=0.05)
        self.bursts = noise.Noise1D(ctx.rng("bursts"), cells=3, octaves=2, time_cells=64)
        self.trains: list = []
        self.train_batch = QuadBatch(16)
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.sky = self.upload(canvas, self.sky_px, BLEND, "sky")
        self.horizon = self.upload(canvas, self.horizon_px, BLEND, "horizon") \
            if self.horizon_px is not None else None
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["glow"], ADD, "glow")
        self.streak_tex = self.upload(canvas, self.sprites["streak"], ADD, "streak")
        self.grain.setup(self, canvas)
        self.sky_px = self.horizon_px = self.sprites = None

    def settings_changed(self, keys: set) -> bool:
        return "horizon" in keys

    def burst(self, t: float) -> float:
        """Rate multiplier 0.4..1.6, changing over a minute or two."""
        n = float(self.bursts.at(np.array([0.5], np.float32), t * 0.01)[0])
        return 0.4 + 1.2 * min(1.0, max(0.0, n * 1.3 + 0.5))

    def update(self, dt: float, t: float) -> None:
        self.t = t
        before = {id(m): m for m in self.meteors.active}
        frequency = float(self.setting("meteor_frequency", 1.0)) * self.burst(t)
        self.meteors.update(dt, frequency, self.width, self.height)
        alive = {id(m) for m in self.meteors.active}
        for key, meteor in before.items():
            if key not in alive and meteor.brightness >= 0.95:
                self.trains.append([meteor, 0.0])      # a fireball leaves a faint train
        for train in self.trains:
            train[1] += dt
        self.trains = [train for train in self.trains if train[1] < TRAIN_SECONDS][-16:]

    def draw(self, canvas) -> None:
        w, h, t, u = self.width, self.height, self.t, self.unit
        canvas.image(self.sky, 0, 0, w, h)
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star_tex, t, w, h, count=count, offset_x=-t * 1.5 * u, wrap=True,
                        twinkle_scale=lambda py: 0.6 + 0.9 * np.clip(py / h, 0, 1) ** 2)
        if self.trains:
            n = len(self.trains)
            hx, hy, ang, length, alpha = (np.empty(n, np.float32) for _ in range(5))
            for i, (m, age) in enumerate(self.trains):
                end = m.speed * m.life
                hx[i] = m.x + math.cos(m.angle) * end
                hy[i] = m.y + math.sin(m.angle) * end + age * 2.0 * u
                ang[i] = m.angle
                length[i] = min(end, m.length)
                alpha[i] = 70.0 * (1.0 - age / TRAIN_SECONDS) ** 2
            self.train_batch.streaks(hx, hy, ang, length, 5.0 * u, (200, 220, 255), alpha)
            self.train_batch.draw(canvas, self.glow_tex, ADD)
        self.meteors.draw(canvas, self.streak_tex, self.glow_tex, u)
        if self.horizon is not None:
            canvas.image(self.horizon, 0, h * 0.8, w, h * 0.2)
        self.grain.draw(canvas)
