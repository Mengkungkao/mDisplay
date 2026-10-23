"""Every scene renders offscreen at several sizes and shapes, animates, holds still
when paused, is deterministic for a seed, keeps circles round, and releases
its textures. (Software renderer on SDL's dummy driver: no screen involved.)"""

import unittest

import numpy as np

import helpers
from app.config import Settings
from app.scenes import catalog, projector

SIZES = ((320, 180), (400, 300), (180, 320))


def run(off, scene_id, seconds=3.0, step=0.1, settings=None, seed=3, quality="eco"):
    clock = helpers.FakeClock()
    settings = settings or Settings()
    settings.set("transition_seconds", 0)
    engine = off.engine(settings, clock, quality=quality, seed=seed)
    engine.request(scene_id)
    off.frame(engine)
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        engine.update(step)
    clock.advance(5)
    return engine, clock


class SceneRenderingTests(unittest.TestCase):
    def setUp(self):
        self.off = helpers.Offscreen(320, 180)
        self.baseline = self.off.canvas.live_textures

    def tearDown(self):
        self.off.close()

    def test_every_scene_draws_at_every_size(self):
        for w, h in SIZES:
            self.off.resize(w, h)
            baseline = self.off.canvas.live_textures
            for scene_id in catalog.SCENE_IDS:
                with self.subTest(scene=scene_id, size=(w, h)):
                    engine, _ = run(self.off, scene_id, seconds=1.0)
                    pixels = self.off.frame(engine)
                    self.assertEqual(pixels.shape[:2], (h, w))
                    self.assertNotIn(scene_id, engine.failed)
                    rgb = pixels[..., :3].astype(np.float32)
                    self.assertGreater(rgb.max(), 40, "nothing visible")
                    # Ambient: dark overall, never a white screen.
                    self.assertLess(rgb.mean(), 110, "too bright for an ambient scene")
                    engine.close()
                    self.assertEqual(self.off.canvas.live_textures, baseline,
                                     f"{scene_id} left textures behind")

    def test_scenes_animate(self):
        for scene_id in catalog.SCENE_IDS:
            with self.subTest(scene=scene_id):
                engine, clock = run(self.off, scene_id, seconds=1.0)
                first = self.off.frame(engine).astype(np.int16)
                for _ in range(30):
                    clock.advance(0.1)
                    engine.update(0.1)
                second = self.off.frame(engine).astype(np.int16)
                changed = (np.abs(first - second).max(axis=2) > 2).mean()
                self.assertGreater(changed, 0.0005, "the scene did not move in 3 s")
                engine.close()

    def test_paused_scenes_hold_still(self):
        for scene_id in catalog.SCENE_IDS:
            with self.subTest(scene=scene_id):
                engine, clock = run(self.off, scene_id, seconds=1.0)
                engine.pause(True)
                first = self.off.frame(engine)
                for _ in range(10):
                    clock.advance(0.1)
                    engine.update(0.0)
                second = self.off.frame(engine)
                self.assertTrue((first == second).all())
                engine.close()

    def test_same_seed_same_picture_other_seed_differs(self):
        for scene_id in ("galaxy", "nebula", "nightsky", "aurora"):
            with self.subTest(scene=scene_id):
                a, _ = run(self.off, scene_id, seed=5)
                pa = self.off.frame(a)
                a.close()
                b, _ = run(self.off, scene_id, seed=5)
                pb = self.off.frame(b)
                b.close()
                c, _ = run(self.off, scene_id, seed=6)
                pc = self.off.frame(c)
                c.close()
                self.assertTrue((pa == pb).all())
                self.assertFalse((pa == pc).all())

    def test_motion_does_not_depend_on_frame_rate(self):
        # Scenes without random events must look the same after 10 s at 24 or 60 fps.
        for scene_id in ("galaxy", "nebula", "aurora", "projector", "starlight"):
            with self.subTest(scene=scene_id):
                slow, _ = run(self.off, scene_id, seconds=10.0, step=1 / 24)
                ps = self.off.frame(slow).astype(np.float32)
                slow.close()
                fast, _ = run(self.off, scene_id, seconds=10.0, step=1 / 60)
                pf = self.off.frame(fast).astype(np.float32)
                fast.close()
                self.assertLess(np.abs(ps - pf).mean(), 0.6)

    def test_density_and_glow_settings_change_the_picture(self):
        settings = Settings()
        engine, _ = run(self.off, "nebula", settings=settings)
        normal = self.off.frame(engine)[..., :3].astype(np.float32).mean()
        settings.set("nebula_intensity", 0.0)
        engine.settings_changed({"nebula_intensity"})
        dim = self.off.frame(engine)[..., :3].astype(np.float32).mean()
        engine.close()
        self.assertLess(dim, normal * 0.6)
        settings = Settings()
        engine, _ = run(self.off, "minimal", settings=settings)
        settings.set("star_density", 2.0)
        many = (self.off.frame(engine)[..., :3].max(axis=2) > 20).sum()
        settings.set("star_density", 0.25)
        few = (self.off.frame(engine)[..., :3].max(axis=2) > 20).sum()
        engine.close()
        self.assertGreater(many, few * 2)

    def test_resizing_keeps_drawing(self):
        for scene_id in catalog.SCENE_IDS:
            with self.subTest(scene=scene_id):
                self.off.resize(320, 180)
                engine, clock = run(self.off, scene_id, seconds=0.5)
                self.off.resize(240, 300)
                engine.resize(240, 300)
                clock.advance(10)
                pixels = self.off.frame(engine)
                clock.advance(10)
                pixels = self.off.frame(engine)
                self.assertEqual(pixels.shape[:2], (300, 240))
                self.assertGreater(pixels[..., :3].max(), 40)
                self.assertNotIn(scene_id, engine.failed)
                engine.close()


if __name__ == "__main__":
    unittest.main()


class ProjectorTests(unittest.TestCase):
    """The galaxy projector turns its whole sky; no layer edge ever reaches the screen."""

    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_options_change_the_picture(self):
        base = Settings()
        base.set("edge_fade", "off")
        engine, _ = run(self.off, "projector", settings=base)
        reference = self.off.frame(engine)[..., :3].astype(np.int16)
        for key, value in (("projector_colors", "sunset"), ("projector_lasers", "off"),
                           ("projector_lasers", "red")):
            with self.subTest(option=(key, value)):
                base.set(key, value)
                changed = self.off.frame(engine)[..., :3].astype(np.int16)
                self.assertGreater(np.abs(changed - reference).max(), 20)
        engine.close()

    def test_turning_never_uncovers_a_corner(self):
        # Each layer is a disc drawn around the screen's centre; the screen's corners
        # are half a diagonal away. The disc's fully lit part must reach past them
        # at its smallest (breathing) size, whatever the angle and screen shape.
        from app.scenes.projector import BREATHE, LAYERS, RIM
        for _rate, _phase, size, _strength in LAYERS:
            lit_radius = 0.5 * size * (1 - BREATHE) * (1 - RIM)     # in diagonals
            self.assertGreater(lit_radius, 0.5)

    def test_corners_are_lit_without_soft_edges(self):
        settings = Settings()
        settings.set("edge_fade", "off")
        settings.set("projector_lasers", "off")
        for w, h in ((320, 180), (180, 320)):
            with self.subTest(size=(w, h)):
                self.off.resize(w, h)
                engine, clock = run(self.off, "projector", settings=settings, seconds=1)
                totals = []
                for _ in range(6):                       # at several angles of the dome
                    for _ in range(50):
                        clock.advance(0.5)
                        engine.update(0.5 * 20)
                    pixels = self.off.frame(engine)[..., :3].astype(float)
                    corners = [pixels[:6, :6], pixels[:6, -6:], pixels[-6:, :6], pixels[-6:, -6:]]
                    totals.append(sum(c.mean() for c in corners) / 4)
                    centre = pixels[h // 2 - 20:h // 2 + 20, w // 2 - 20:w // 2 + 20].mean()
                engine.close()
                # Nebula is patchy, so compare averages over angles, not single patches;
                # the projector's lens dims the corners on purpose.
                lens = 1.0 - projector.LENS_FALLOFF
                self.assertGreater(np.mean(totals), 0.25 * lens * centre)

    def test_rotation_options(self):
        from app.scenes.projector import TURN_DEGREES_PER_SECOND
        settings = Settings()
        engine, _ = run(self.off, "projector", settings=settings, seconds=10)
        scene = (engine.current or engine.incoming).scene
        self.assertAlmostEqual(scene.turn(), scene.t * TURN_DEGREES_PER_SECOND["slow"])
        settings.set("projector_rotation", "off")
        self.assertEqual(scene.turn(), 0.0)
        engine.close()
