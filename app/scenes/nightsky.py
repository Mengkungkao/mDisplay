"""Scene B — Night sky: twinkling stars, the Milky Way, drifting clouds, a horizon.

Stars twinkle independently (two incommensurate rates per star) and more
strongly near the horizon, where starlight crosses more air. The sky drifts
slowly sideways; clouds drift faster, in front of it. This is an
illustrative sky, not a map of the real one.
"""

from __future__ import annotations

import numpy as np

from ..gfx import noise
from ..gfx.canvas import ADD, BLEND, NONE
from .base import Scene
from .parts import (Grain, Meteors, StarField, add_trees, common_sprites, density_count,
                    ridge_line, silhouette, sky_gradient)

SKY = [(0.0, (2, 4, 12)), (0.45, (5, 10, 26)), (0.78, (12, 24, 50)), (0.9, (26, 38, 64)),
       (1.0, (30, 40, 62))]


class NightSkyScene(Scene):
    id = "nightsky"
    STARS = 1500
    BRIGHT = 24

    def prepare(self) -> None:
        ctx = self.ctx
        q = ctx.quality
        w, h = self.width, self.height
        tex = min(1.0, q.texture + 0.25)
        sky = 1.0 if self.software else tex           # software: draw it 1:1
        gw, gh = max(64, int(w * sky)), max(64, int(h * sky))
        self.gradient_px = sky_gradient(ctx.rng("sky"), gw, gh, SKY, dither=1.2)
        self.horizon_h = 0.0
        self.horizon_px = None
        if self.setting("horizon", True):
            hh = max(32, int(h * 0.24))
            profile = ridge_line(ctx.rng("hills"), max(64, w), base=h * 0.045, amplitude=h * 0.07,
                                 cells=5)
            profile = add_trees(ctx.rng("trees"), profile, count=int(w / 22), height=h * 0.075,
                                width_px=h * 0.032, clustered=True)
            self.horizon_px = silhouette(np.minimum(profile, hh - 1), hh, (3, 4, 9),
                                         rim=(16, 22, 36), rim_width=1.6 * max(1.0, self.unit))
            self.horizon_h = hh
        # The Milky Way: a soft band of unresolved stars, star clouds stretched along
        # it and a broken dark rift, tileable across the width.
        mw_w = max(128, int(w * 0.6 * tex))
        mw_h = max(64, int(h * 0.6 * tex))
        self.milkyway_px = milky_way(ctx.rng("milkyway"), mw_w, mw_h, q.detail)
        # Faint stars crowd into the band, as they do in the real Milky Way.
        brng = ctx.rng("band-stars")
        weights = self.milkyway_px[..., 3].astype(np.float64).ravel() ** 1.5
        picks = brng.choice(weights.size, int(500 * q.stars), p=weights / weights.sum())
        bx = (picks % mw_w + brng.random(len(picks))) / mw_w
        by = -0.08 + 0.9 * (picks // mw_w + brng.random(len(picks))) / mw_h
        self.band_stars = StarField(brng, 0, size=(1.2, 3.6), twinkle=0.3, saturation=0.4,
                                    faintness=2.0, positions=(bx, by))
        self.milkyway_px = self.fit(self.milkyway_px, w, h * 0.9)
        # Clouds: a tileable layer, dark where dense, faintly lit underneath
        # (light from towns below the horizon), faded at its top and bottom.
        self.cloud_px = None
        if self.setting("clouds", True):
            cw, ch = max(128, int(w * 0.7 * tex)), max(64, int(h * 0.3 * tex))
            self.cloud_px = clouds(ctx.rng("clouds"), cw, ch, q.detail)
            # Two layers at two scales; on the software renderer each is pre-scaled.
            self.cloud_far_px = self.fit(self.cloud_px, w * 1.2, h * 0.34)
            self.cloud_near_px = self.fit(self.cloud_px, w * 1.5, h * 0.374)
        capacity, _ = density_count(self.STARS, q, 2.0)
        self.stars = StarField(ctx.rng("stars"), capacity, region=(0, 0, 1, 0.95),
                               size=(1.5, 6.0), twinkle=0.45, twinkle_speed=(0.2, 1.6),
                               saturation=0.55, y_weight=lambda yy: 1.0 - 0.5 * yy ** 3)
        self.bright = StarField(ctx.rng("bright"), self.BRIGHT, region=(0, 0.02, 1, 0.8),
                                size=(12.0, 30.0), twinkle=0.35, twinkle_speed=(0.3, 1.4),
                                saturation=0.6, faintness=0.35)
        # Gentle motion: nothing crosses the sky; the stars only fade and twinkle.
        self.meteors = None if self.gentle else Meteors(
            ctx.rng("meteors"), per_minute=1.5, max_active=2, min_gap=4.0,
            area=(0.05, 0.04, 0.95, 0.5))
        if self.gentle:
            for field in (self.stars, self.bright, self.band_stars):
                field.calm()
        self.grain = Grain(ctx.rng("grain"), q.detail >= 1)
        self.sprites = common_sprites(q)

    def setup(self, canvas) -> None:
        self.gradient = self.upload(canvas, self.gradient_px, NONE, "sky")
        self.milkyway = self.upload(canvas, self.milkyway_px, ADD, "milkyway")
        self.horizon = self.upload(canvas, self.horizon_px, BLEND, "horizon") \
            if self.horizon_px is not None else None
        self.cloud = self.cloud_near = None
        if self.cloud_px is not None:
            self.cloud = self.upload(canvas, self.cloud_far_px, BLEND, "clouds")
            self.cloud_near = self.cloud if self.cloud_near_px is self.cloud_px else \
                self.upload(canvas, self.cloud_near_px, BLEND, "clouds-near")
        self.star_tex = self.upload(canvas, self.sprites["star"], name="star")
        self.spike_tex = self.upload(canvas, self.sprites["spike"], name="spike")
        self.glow_tex = self.upload(canvas, self.sprites["glow"], name="glow")
        self.streak_tex = self.upload(canvas, self.sprites["streak"], name="streak")
        self.grain.setup(self, canvas)
        self.gradient_px = self.milkyway_px = self.horizon_px = self.cloud_px = None
        self.cloud_far_px = self.cloud_near_px = None
        self.sprites = None

    def settings_changed(self, keys: set) -> bool:
        return bool(keys & {"clouds", "horizon"})

    def update(self, dt: float, t: float) -> None:
        self.t = t
        if self.meteors is not None:
            self.meteors.update(dt, float(self.setting("meteor_frequency", 1.0)), self.width,
                                self.height * (1.0 - 0.2 * bool(self.horizon)))

    def draw(self, canvas) -> None:
        w, h, t, u = self.width, self.height, self.t, self.unit
        canvas.image(self.gradient, 0, 0, w, h)
        moving = 0.0 if self.gentle else 1.0     # gentle: the sky holds still
        drift = -t * 2.6 * u * moving
        glow = float(self.setting("nebula_intensity", 1.0))
        if glow > 0:
            level = int(min(255, 150 * glow))
            mw_w, mw_h = (self.milkyway.width, self.milkyway.height) if self.software \
                else (w, h * 0.9)
            canvas.tiled(self.milkyway, drift, -h * 0.08, mw_w, mw_h, color=(level,) * 3,
                         area=(0, 0, w, h))
        _, count = density_count(self.STARS, self.ctx.quality, float(self.setting("star_density", 1.0)))
        sky_h = h
        self.stars.draw(canvas, self.star_tex, t, w, sky_h, count=count, offset_x=drift, wrap=True,
                        twinkle_scale=lambda py: 0.55 + 1.1 * np.clip(py / h, 0, 1) ** 2)
        if glow > 0:
            self.band_stars.draw(canvas, self.star_tex, t, w, sky_h, offset_x=drift, wrap=True,
                                 alpha=min(1.0, 0.8 * glow))
        self.bright.draw(canvas, self.spike_tex, t, w, sky_h, offset_x=drift, wrap=True,
                         alpha=0.85)
        if self.meteors is not None:
            self.meteors.draw(canvas, self.streak_tex, self.glow_tex, u)
        if self.cloud is not None:
            far, near = self.cloud, self.cloud_near
            fw, fh = (far.width, far.height) if self.software else (w * 1.2, h * 0.34)
            nw, nh = (near.width, near.height) if self.software else (w * 1.5, h * 0.374)
            canvas.tiled(far, -t * 9.0 * u * moving, h * 0.44, fw, fh, area=(0, h * 0.44, w, fh))
            canvas.tiled(near, -t * 14.0 * u * moving + w * 0.37, h * 0.58, nw, nh, alpha=200,
                         area=(0, h * 0.58, w, nh))
        if self.horizon is not None:
            canvas.image(self.horizon, 0, h * 0.76, w, h * 0.24)
        self.grain.draw(canvas)


def milky_way(rng, width: int, height: int, detail: int) -> np.ndarray:
    """RGBA band: broad glow, grainy star clouds stretched along the band, a dark rift.

    Every noise field is sampled over a whole number of its periods across the
    width, so the band tiles without a seam as the sky drifts.
    """
    from ..gfx.sprites import rgba
    x = (np.arange(width, dtype=np.float32) + 0.5) / width
    y = (np.arange(height, dtype=np.float32)[:, None] + 0.5) / height
    centre = 0.5 + 0.09 * np.sin(2 * np.pi * x + 0.6)[None, :]
    offset = y - centre
    clouds_f = noise.FBM(rng, 3, 6, 4 + detail)       # stretched along the band
    grain_f = noise.FBM(rng, 40, 40, 2)
    wobble_f = noise.FBM(rng, 3, 1, 3)
    broken_f = noise.FBM(rng, 6, 4, 3 + detail)
    v = (offset + 0.5) * 6.0
    star_clouds = noise.contrast(clouds_f.at(x[None, :] * 3.0, v) * 0.5 + 0.5, 0.35, 0.75)
    grain = noise.contrast(grain_f.at(x[None, :] * 40.0, y * 40.0) * 0.5 + 0.5, 0.45, 0.8)
    wobble = wobble_f.at(x * 3.0, np.full_like(x, 0.5))[None, :] * 0.035
    rift = np.exp(-((offset - 0.012 - wobble) ** 2) / (2 * 0.018 ** 2))
    broken = noise.contrast(broken_f.at(x[None, :] * 6.0, v * 0.6) * 0.5 + 0.5, 0.35, 0.6)
    band = np.exp(-(offset ** 2) / (2 * 0.085 ** 2))
    halo = np.exp(-(offset ** 2) / (2 * 0.2 ** 2))
    light = band * (0.25 + 0.75 * star_clouds) * (0.6 + 0.4 * grain) + 0.16 * halo
    light *= 1.0 - 0.8 * rift * broken
    rgb = np.empty((height, width, 3), np.float32)
    rgb[..., 0] = 0.86 + 0.14 * band
    rgb[..., 1] = 0.86 + 0.06 * band
    rgb[..., 2] = 1.0 - 0.12 * band
    return rgba(rgb, np.clip(light * 0.5, 0, 1))


def clouds(rng, width: int, height: int, detail: int) -> np.ndarray:
    from ..gfx.sprites import rgba
    density = noise.fbm_image(rng, width, height, cells_across=4, octaves=4 + detail)
    vertical = np.clip(np.sin(np.linspace(0, np.pi, height, dtype=np.float32)), 0, 1)[:, None] ** 1.2
    alpha = noise.contrast(density, 0.46, 0.66) * vertical
    below = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None] ** 2
    lit = np.clip((1.0 - alpha) * 0.6 + below * 0.5, 0, 1)
    dark = np.array([7, 9, 17], np.float32) / 255.0
    glow = np.array([46, 42, 52], np.float32) / 255.0
    rgb = dark + (glow - dark) * lit[..., None]
    return rgba(rgb, alpha * 0.95)
