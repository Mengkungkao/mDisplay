"""The refined scenes (0.3.0): the galaxy seen from inside, the slower nebula, the
aurora from below and the projector's lens. Offscreen, software renderer."""

import math
import unittest

import numpy as np

import helpers
from app.config import Settings
from app.scenes import aurora, milkyway, nebula, projector
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


class AuroraFromBelowTests(unittest.TestCase):
    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_rays_converge_on_the_zenith(self):
        engine, _ = run(self.off, "aurora")
        scene = showing(engine)
        w, h = scene.width, scene.height
        zx, zy = aurora.ZENITH[0] * w, aurora.ZENITH[1] * h
        for curtain in scene.curtains:
            curtain.update_mesh(10.0, w, h, 1.0)            # the GPU path's geometry
            v = curtain.mesh.vertices.reshape(curtain.rays, curtain.rows + 1, 3)
            bottom = np.stack([v["x"][:, 0].mean(axis=1), v["y"][:, 0].mean(axis=1)], axis=1)
            top = np.stack([v["x"][:, -1].mean(axis=1), v["y"][:, -1].mean(axis=1)], axis=1)
            to_zenith = np.array([zx, zy]) - bottom
            along = top - bottom
            cos = (along * to_zenith).sum(axis=1) / (
                np.linalg.norm(along, axis=1) * np.linalg.norm(to_zenith, axis=1))
            self.assertGreater(np.median(cos), 0.99)        # every ray points at the zenith
            self.assertTrue((np.hypot(*(top - [zx, zy]).T) < np.hypot(*(bottom - [zx, zy]).T)).all())
        engine.close()

    def test_the_lower_border_is_on_screen_and_the_horizon_is_thin(self):
        engine, _ = run(self.off, "aurora")
        scene = showing(engine)
        main = scene.curtains[0]
        main.update_mesh(10.0, scene.width, scene.height, 1.0)
        v = main.mesh.vertices.reshape(main.rays, main.rows + 1, 3)
        bright_row = v["y"][:, 1].mean(axis=1)              # the bright lower edge
        u = main.positions(10.0 * main.speed)
        middle = np.abs(u - 0.5) < 0.2
        self.assertTrue((bright_row[middle] < scene.height).all())
        self.assertLessEqual(scene.horizon.height, 0.1 * scene.height + 1)
        engine.close()

    def test_the_software_painter_draws_what_the_meshes_draw(self):
        engine, _ = run(self.off, "aurora")
        scene = showing(engine)
        canvas = self.off.canvas
        h, w = scene.painter.image.shape[:2]
        black = np.zeros((h, w, 4), np.uint8)
        painter = aurora.SoftwareCurtains(scene.curtains, black)
        for t in (10.0, 75.0):
            with self.subTest(t=t):
                painted = painter.paint(t, 0.8)[..., :3].astype(np.float32)
                target = canvas.target(w, h, "reference")
                with canvas.into(target):
                    canvas.clear((0, 0, 0), alpha=255)
                    for curtain in scene.curtains:
                        curtain.update_mesh(t, w, h, 0.8)
                        curtain.mesh.draw(canvas, None, aurora.ADD)
                    drawn = canvas.read_rgba()[..., :3].astype(np.float32)
                target.destroy()
                a, b = painted.mean(axis=2).ravel(), drawn.mean(axis=2).ravel()
                self.assertGreater(np.corrcoef(a, b)[0, 1], 0.8)
                self.assertLess(abs(a.mean() - b.mean()), 0.35 * b.mean())
        engine.close()

    def test_stars_show_between_the_rays(self):
        engine, _ = run(self.off, "aurora", seconds=2.0)
        pixels = self.off.frame(engine)[..., :3].astype(np.int16)
        lit = pixels.max(axis=2)
        dark = (lit < 25).mean()
        self.assertGreater(dark, 0.15, "the curtains cover the whole sky")
        engine.close()


class ProjectorLensTests(unittest.TestCase):
    def test_the_lens_dims_the_corners_not_the_middle(self):
        image = projector.lens(160, 90)[..., 0].astype(np.float32)
        self.assertEqual(image[45, 80], 255)
        self.assertAlmostEqual(image[0, 0] / 255.0, 1.0 - projector.LENS_FALLOFF, delta=0.05)

    def test_points_soften_towards_the_edges(self):
        r = np.array([0.0, 0.5, 1.0], np.float32)
        defocus = projector.ProjectorScene.defocus(r)
        self.assertAlmostEqual(float(defocus[0]), 1.0)
        self.assertTrue((np.diff(defocus) > 0).all())
        self.assertAlmostEqual(float(defocus[2]), 1.0 + projector.LENS_DEFOCUS, places=5)

    def test_clouds_are_uneven_not_a_uniform_veil(self):
        alpha = projector.nebula_disc(np.random.default_rng(2), 256, 0, 3)[..., 3] / 255.0
        y, x = np.mgrid[0:256, 0:256]
        inside = np.hypot(x - 127.5, y - 127.5) < 100
        self.assertGreater((alpha[inside] < 0.05).mean(), 0.1)     # empty patches
        self.assertGreater((alpha[inside] > 0.4).mean(), 0.05)     # and dense clouds
        rgb = projector.nebula_disc(np.random.default_rng(2), 256, 0, 3)[..., :3]
        self.assertGreater(rgb[..., 0][inside].std(), 5)          # colour varies inside

    def test_laser_stars_are_tiny(self):
        # The largest laser star at 1080p in the middle of the picture (before blur).
        half = projector.LASER_SIZE * 0.75 * 1.0 * 1.25
        self.assertLess(2 * half, 7.0)


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
            texture = canvas.texture(flat, aurora.ADD, name="flat")
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
