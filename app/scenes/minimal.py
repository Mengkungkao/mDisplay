"""Scene G — Minimal: a nearly black sky with sparse, dim stars for a dark room.

The lightest scene: one star batch, a rare faint meteor, 24 frames a second.
In gentle motion nothing moves: no meteor, no drift; the stars only twinkle.
"""

from __future__ import annotations

from .base import Scene
from .parts import Meteors, StarField, common_sprites, density_count


class MinimalScene(Scene):
    id = "minimal"
    max_fps = 24
    BACKGROUND = (2, 3, 7)

    def prepare(self) -> None:
        rng = self.ctx.rng("minimal")
        capacity, _ = density_count(170, self.ctx.quality, 2.0)
        self.stars = StarField(rng, capacity, size=(1.3, 4.2), twinkle=0.22,
                               twinkle_speed=(0.03, 0.22), saturation=0.35, faintness=2.6)
        self.meteors = None if self.gentle else Meteors(
            self.ctx.rng("minimal.meteors"), per_minute=0.25, max_active=1, min_gap=60.0,
            brightness=(0.25, 0.45), fireball=0.0, width=2.4)
        self.sprites = common_sprites(self.ctx.quality)

    def setup(self, canvas) -> None:
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.glow_tex = self.upload(canvas, self.sprites["glow"], name="glow")
        self.streak_tex = self.upload(canvas, self.sprites["streak"], name="streak")
        self.sprites = None

    def update(self, dt: float, t: float) -> None:
        self.t = t
        if self.meteors is not None:
            self.meteors.update(dt, float(self.setting("meteor_frequency", 1.0)), self.width,
                                self.height)

    def draw(self, canvas) -> None:
        canvas.clear(self.BACKGROUND)
        _, count = density_count(170, self.ctx.quality, float(self.setting("star_density", 1.0)))
        drift = 0.0 if self.gentle else -self.t * 1.2 * self.unit   # a screen width an hour
        self.stars.draw(canvas, self.star_tex, self.t, self.width, self.height, alpha=0.55,
                        count=count, offset_x=drift, wrap=True)
        if self.meteors is not None:
            self.meteors.draw(canvas, self.streak_tex, self.glow_tex, self.unit, alpha=0.7)
