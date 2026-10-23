"""The refined scenes (0.3.0): the galaxy seen from inside, the slower nebula, the
realistic aurora over a lake (0.4.0). Offscreen, software renderer."""

import math
import unittest

import numpy as np

import helpers
from app.config import Settings
from app.gfx.canvas import ADD
from app.scenes import aurora, milkyway, nebula
from app.scenes.base import QUALITY, Cancelled, SceneContext
from app.scenes.galaxy import OutsideGalaxy


def run(off, scene_id, seconds=0.2, step=0.1, gentle=False, **values):
    clock = helpers.FakeClock()
    settings = Settings()
    settings.set("transition_seconds", 0)
    for key, value in values.items():
        settings.set(key, value)
    engine = off.engine(settings, clock, gentle=gentle)
    engine.request(scene_id)
    off.frame(engine)
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        engine.update(step)
    return engine, settings


def showing(engine):
    return (engine.incoming or engine.current).scene


class InsideGalaxyTests(unittest.TestCase):
    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_the_galaxy_is_seen_from_inside_by_default_and_outside_on_request(self):
        engine, settings = run(self.off, "galaxy")
        self.assertIsInstance(showing(engine), milkyway.InsideGalaxy)
        settings.set("galaxy_view", "outside")
        engine.settings_changed({"galaxy_view"})
        engine.update(0.1)
        self.off.frame(engine)
        self.assertIsInstance(showing(engine), OutsideGalaxy)
        engine.close()

    def test_a_band_crosses_the_sky_warmer_towards_the_core(self):
        image, light = milkyway.panorama(np.random.default_rng(4), 832, 180, 0)
        rgb = image[..., :3].astype(np.float32)
        # Brighter along the band than at the top and bottom of the sky.
        rows = light.mean(axis=1)
        self.assertGreater(rows.max(), 4 * min(rows[:10].mean(), rows[-10:].mean()))
        # The core's columns are warmer (red over blue) than the band far from it.
        width = image.shape[1]
        core = int(milkyway.CORE_AT * width)
        far = (core + width // 2) % width
        warmth = rgb[..., 0] / np.maximum(1.0, rgb[..., 2])
        self.assertGreater(warmth[:, core - 4:core + 4].mean(), warmth[:, far - 4:far + 4].mean())

    def test_the_panorama_is_seamless_across_its_width(self):
        _, light = milkyway.panorama(np.random.default_rng(5), 832, 180, 0)
        seam = np.abs(light[:, 0] - light[:, -1]).mean()
        neighbours = np.abs(light[:, 0] - light[:, 1]).mean()
        self.assertLess(seam, 3 * neighbours + 1e-3)

    def test_the_band_drifts_smoothly_below_a_pixel(self):
        """Software: two whole-pixel copies blended, so passing a whole pixel is no jump."""
        engine, _ = run(self.off, "galaxy", star_density=0.25)
        scene = showing(engine)
        rate = scene.drift(1.0)                          # pixels a second
        boundary = (math.floor(scene.drift(scene.t)) + 1) / rate
        frames = []
        for t in (boundary - 0.3 / rate, boundary - 0.1 / rate, boundary + 0.1 / rate):
            engine.update(t - scene.t)
            frames.append(self.off.frame(engine).astype(np.int16))
        before = np.abs(frames[1] - frames[0]).mean()    # 0.2 px apart, same whole pixel
        across = np.abs(frames[2] - frames[1]).mean()    # 0.2 px apart, across a whole pixel
        # Measured: blended 0.035 then 0.023; one whole-pixel copy 0.005 then 0.133.
        self.assertLess(across, max(before, 0.01) * 2.5 + 0.02)
        engine.close()

    def test_a_long_preparation_stops_when_no_longer_wanted(self):
        ctx = SceneContext(320, 180, QUALITY["eco"], Settings(), seed=3, accelerated=False,
                           cancelled=lambda: True)
        with self.assertRaises(Cancelled):
            milkyway.InsideGalaxy(ctx).prepare()

    def test_the_engine_cancels_a_preparation_it_no_longer_wants(self):
        engine, _ = run(self.off, "nebula")
        first = engine._context()
        second = engine._context()       # a newer choice replaces the first
        self.assertTrue(first.cancelled())
        self.assertFalse(second.cancelled())
        engine.close()
        self.assertTrue(second.cancelled())


class NebulaSpeedTests(unittest.TestCase):
    def test_half_speed_in_full_and_slower_again_in_gentle(self):
        self.assertAlmostEqual(nebula.DRIFT["full"], 0.5)
        self.assertLess(nebula.DRIFT["gentle"], nebula.DRIFT["full"])
        self.assertGreaterEqual(nebula.COLOR_CYCLE_SECONDS["full"], 2 * 420.0)
        self.assertGreater(nebula.COLOR_CYCLE_SECONDS["gentle"], nebula.COLOR_CYCLE_SECONDS["full"])

    def test_gentle_changes_the_picture_less_over_a_minute(self):
        off = helpers.Offscreen(320, 180)
        try:
            change = {}
            for gentle in (False, True):
                engine, _ = run(off, "nebula", gentle=gentle)
                first = off.frame(engine).astype(np.int16)
                for _ in range(60):
                    engine.update(1.0)
                change[gentle] = np.abs(off.frame(engine).astype(np.int16) - first).mean()
                engine.close()
            self.assertLess(change[True], change[False])
        finally:
            off.close()


class AuroraTests(unittest.TestCase):
    """The aurora over a lake: colours by height, the shore, and pictures made in the
    background and blended."""

    @classmethod
    def setUpClass(cls):
        cls.sky = aurora.AuroraSky(np.random.default_rng(7), 320, 180, True, 1)
        cls.image = cls.sky.render(20.0)[..., :3].astype(np.float32)

    def region(self, x0, x1, y0, y1):
        h, w = self.image.shape[:2]
        return self.image[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].reshape(-1, 3).mean(axis=0)

    def test_green_low_pink_higher_teal_on_the_right_dark_top_left(self):
        low = self.region(0.2, 0.5, 0.66, 0.78)          # above the shore, left of centre
        high = self.region(0.25, 0.45, 0.3, 0.45)        # higher up on the left
        right = self.region(0.8, 0.95, 0.35, 0.5)        # the right side, mid-height
        corner = self.region(0.0, 0.12, 0.0, 0.2)        # top left: night sky
        self.assertGreater(low[1], low[2])               # green dominates low down
        self.assertGreater(high[0], high[1])             # pink (red over green) higher up
        self.assertGreater(right[1] + right[2], 2 * right[0])   # teal on the right
        self.assertLess(corner.mean(), 30)
        self.assertGreater(self.image.max(), 200)        # bright where curtains overlap

    def test_the_shore_is_dark_and_the_lake_reflects_the_sky(self):
        sky = self.sky
        y0 = sky.horizon
        self.assertTrue(sky.trees.any())
        trees = self.image[sky.trees]
        self.assertLess(trees.max(), 20)
        above = self.image[y0 - 12:y0 - 6].mean(axis=(0, 2))       # per column, above
        below = self.image[y0 + 2:y0 + 8].mean(axis=(0, 2))        # and just below the shore
        self.assertLess(below.mean(), above.mean())                 # dimmer: a reflection
        self.assertGreater(np.corrcoef(above, below)[0, 1], 0.5)    # of the same light

    def test_without_the_mountains_setting_it_is_all_sky(self):
        sky = aurora.AuroraSky(np.random.default_rng(7), 160, 90, False, 0)
        self.assertGreaterEqual(sky.horizon, sky.height)
        self.assertIsNone(sky.trees)

    def test_a_picture_depends_only_on_its_time(self):
        a, b = self.sky.render(33.0), self.sky.render(33.0)
        self.assertTrue((a == b).all())
        self.assertFalse((a == self.sky.render(40.0)).all())

    def test_blending_between_pictures_has_no_jump(self):
        off = helpers.Offscreen(320, 180)
        try:
            engine, _ = run(off, "aurora", seconds=0.1)
            scene = showing(engine)
            boundary = scene.frames[1][0] / scene.rate          # real seconds to the 2nd picture
            frames = []
            for t in (boundary - 0.3, boundary - 0.15, boundary, boundary + 0.15):
                engine.update(t - scene.t)
                frames.append(off.frame(engine).astype(np.int16))
            steps = [np.abs(b - a).mean() for a, b in zip(frames, frames[1:])]
            self.assertLess(max(steps), 2.5 * min(steps) + 0.3)
            engine.close()
        finally:
            off.close()

    def test_pictures_come_from_the_background_and_the_aurora_waits_for_them(self):
        off = helpers.Offscreen(320, 180)
        try:
            from concurrent.futures import Future
            submitted = []

            def background(fn, *args):
                submitted.append(args)
                return Future()                              # never finishes: a slow worker
            settings = Settings()
            settings.set("transition_seconds", 0)
            engine = off.engine(settings, helpers.FakeClock())
            make = engine.make_context

            def with_background():
                context = make()
                context.background = background
                return context
            engine.make_context = with_background
            engine.request("aurora")
            off.frame(engine)
            scene = showing(engine)
            self.assertEqual(len(submitted), 1)              # the next picture was asked for
            for _ in range(50):
                engine.update(0.5)
                off.frame(engine)
            self.assertEqual(len(submitted), 1)              # once, not again and again
            self.assertLessEqual(scene.tau, scene.frames[-1][0])   # waited, did not run ahead
            engine.close()
        finally:
            off.close()


class TiledSeamTests(unittest.TestCase):
    """Software renderer: tiles meet edge to edge at any offset (it truncates
    rectangles towards zero, which made a tile left of the origin overlap the next)."""

    def test_no_bright_seam_between_tiles(self):
        off = helpers.Offscreen(160, 40)
        try:
            canvas = off.canvas
            flat = np.zeros((20, 50, 4), np.uint8)
            flat[..., :3] = 255
            flat[..., 3] = 60
            texture = canvas.texture(flat, ADD, name="flat")
            for offset in (-30.6, -12.25, 7.4, 33.9):
                with self.subTest(offset=offset):
                    with canvas.into(off.target):
                        canvas.clear((0, 0, 0))
                        canvas.tiled(texture, offset, 0.0, 50, 20)
                        pixels = canvas.read_rgba()[..., 0].astype(np.int16)
                    self.assertEqual(int(pixels.max() - pixels.min()), 0, "a seam or a gap")
            texture.destroy()
        finally:
            off.close()


if __name__ == "__main__":
    unittest.main()
