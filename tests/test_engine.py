"""The scene engine: selection, transitions, rotation, pause, sleep, failures, clean-up."""

import unittest

import numpy as np

import helpers
from app.config import Settings
from app.engine import Engine
from app.scenes import catalog
from app.scenes.base import Scene


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = helpers.Offscreen(160, 90)

    @classmethod
    def tearDownClass(cls):
        cls.off.close()

    def setUp(self):
        self.clock = helpers.FakeClock()
        self.settings = Settings()
        self.settings.set("transition_seconds", 2.0)
        self.engine = self.off.engine(self.settings, self.clock)
        self.baseline = self.off.canvas.live_textures

    def tearDown(self):
        self.engine.close()

    def show(self, scene_id):
        self.engine.request(scene_id)
        self.off.frame(self.engine)
        self.clock.advance(30)
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, scene_id)

    def test_registry_lists_eight_unique_scenes(self):
        self.assertEqual(len(catalog.SCENE_IDS), 8)
        self.assertEqual(len(set(catalog.SCENE_IDS)), 8)
        self.assertEqual(set(catalog.SCENE_IDS), {"galaxy", "nightsky", "nebula", "aurora", "solar",
                                                 "meteors", "projector", "minimal"})
        for info in catalog.SCENES:
            cls = catalog.load(info.id)
            self.assertTrue(issubclass(cls, Scene))
            self.assertEqual(cls.id, info.id)

    def test_first_scene_fades_in_from_black(self):
        self.engine.request("minimal")
        self.off.frame(self.engine)
        self.assertEqual(self.engine.scene_id, "minimal")
        self.assertIsNone(self.engine.showing_id)
        self.assertLess(self.engine.fade_progress(), 1.0)
        self.clock.advance(5)
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "minimal")

    def test_transition_cross_fades_and_closes_the_old_scene(self):
        self.show("minimal")
        old = self.engine.current.scene
        self.engine.request("nightsky")
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "minimal")       # still fading
        self.clock.advance(1.0)
        self.assertAlmostEqual(self.engine.fade_progress(), 0.5)
        self.clock.advance(1.5)
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "nightsky")
        self.assertEqual(old.textures, [])                        # released

    def test_zero_transition_cuts(self):
        self.settings.set("transition_seconds", 0)
        self.show("minimal")
        self.engine.request("nebula")
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "nebula")

    def test_next_and_previous_wrap(self):
        self.show("minimal")
        self.assertEqual(self.engine.step(+1), "galaxy")
        self.engine.close()
        self.engine = self.off.engine(self.settings, self.clock)
        self.show("galaxy")
        self.assertEqual(self.engine.step(-1), "minimal")

    def test_requesting_the_shown_scene_does_nothing(self):
        self.show("minimal")
        self.assertFalse(self.engine.request("minimal"))
        self.assertFalse(self.engine.request("no-such-scene"))

    def test_automatic_rotation(self):
        self.settings.set("auto_rotate", True)
        self.settings.set("rotate_minutes", 5)
        self.engine.settings_changed({"auto_rotate"})
        self.show("minimal")
        self.engine.last_change = self.clock()
        self.clock.advance(299)
        self.engine.timers()
        self.assertEqual(self.engine.scene_id, "minimal")
        self.clock.advance(2)
        self.engine.timers()
        self.assertEqual(self.engine.scene_id, "galaxy")

    def test_rotation_waits_while_paused(self):
        self.settings.set("auto_rotate", True)
        self.settings.set("rotate_minutes", 1)
        self.show("minimal")
        self.engine.pause(True)
        self.clock.advance(120)
        self.engine.timers()
        self.assertEqual(self.engine.scene_id, "minimal")

    def test_sleep_timer_reports_once(self):
        self.show("minimal")
        self.engine.set_sleep(15)
        self.clock.advance(15 * 60 - 1)
        self.assertIsNone(self.engine.timers())
        self.assertAlmostEqual(self.engine.next_timer(), 1.0)
        self.clock.advance(2)
        self.assertEqual(self.engine.timers(), "sleep")
        self.assertIsNone(self.engine.timers())
        self.assertIsNone(self.engine.sleep_remaining())

    def test_paused_scene_time_stands_still(self):
        self.show("minimal")
        slot = self.engine.current
        self.engine.update(0.5)
        t = slot.t
        self.engine.pause(True)
        self.assertFalse(self.engine.animating)
        self.engine.update(0.0)
        self.assertEqual(slot.t, t)
        first = self.off.frame(self.engine)
        second = self.off.frame(self.engine)
        self.assertTrue((first == second).all())

    def test_a_failing_scene_is_reported_and_minimal_takes_over(self):
        notices = []
        self.engine.on_notice = notices.append

        class Broken(Scene):
            id = "galaxy"

            def draw(self, canvas):
                raise RuntimeError("boom")

        original = catalog.load
        catalog.load = lambda scene_id: Broken if scene_id == "galaxy" else original(scene_id)
        try:
            self.engine.request("galaxy")
            self.off.frame(self.engine)
            self.clock.advance(5)
            self.off.frame(self.engine)
            self.off.frame(self.engine)
        finally:
            catalog.load = original
        self.assertIn("galaxy", self.engine.failed)
        self.assertTrue(any("Galaxy could not be shown" in n for n in notices))
        self.clock.advance(5)
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "minimal")

    def test_preparation_failure_keeps_the_current_scene(self):
        self.show("minimal")

        class Unpreparable(Scene):
            id = "nebula"

            def prepare(self):
                raise MemoryError("no room")

        original = catalog.load
        catalog.load = lambda scene_id: Unpreparable if scene_id == "nebula" else original(scene_id)
        try:
            self.engine.request("nebula")
            self.off.frame(self.engine)
        finally:
            catalog.load = original
        self.assertEqual(self.engine.showing_id, "minimal")
        self.assertIn("nebula", self.engine.failed)

    def test_close_releases_every_texture(self):
        for scene_id in ("galaxy", "solar"):
            self.engine.request(scene_id)
            self.off.frame(self.engine)
            self.clock.advance(10)
            self.off.frame(self.engine)
        self.engine.close()
        self.assertEqual(self.off.canvas.live_textures, self.baseline)

    def test_brightness_dims_the_frame(self):
        self.settings.set("transition_seconds", 0)
        self.show("nebula")
        full = self.off.frame(self.engine, 1.0)[..., :3].astype(float).mean()
        dim = self.off.frame(self.engine, 0.3)[..., :3].astype(float).mean()
        self.assertGreater(full, 0)
        self.assertAlmostEqual(dim / full, 0.3, delta=0.08)

    def test_quality_or_size_rebuild_keeps_the_scene(self):
        self.show("nightsky")
        self.engine._rebuild("nightsky")
        self.off.frame(self.engine)
        self.clock.advance(10)
        self.off.frame(self.engine)
        self.assertEqual(self.engine.showing_id, "nightsky")


if __name__ == "__main__":
    unittest.main()


class EdgeTests(unittest.TestCase):
    """Soft edges: the picture fades to black at the screen's border, no visible rectangle."""

    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def frame(self, mode):
        settings = Settings()
        settings.set("transition_seconds", 0)
        settings.set("edge_fade", mode)
        clock = helpers.FakeClock()
        engine = self.off.engine(settings, clock)
        engine.request("projector")
        self.off.frame(engine)
        clock.advance(10)
        pixels = self.off.frame(engine)[..., :3].astype(float)
        engine.close()
        return pixels

    def test_border_is_black_with_soft_edges_and_lit_without(self):
        for mode in ("soft", "strong"):
            with self.subTest(mode=mode):
                pixels = self.frame(mode)
                border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
                self.assertLess(border.max(), 12, "the screen's edge shows")
                self.assertGreater(pixels[60:120, 100:220].mean(), 3)
        plain = self.frame("off")
        border = np.concatenate([plain[0], plain[-1], plain[:, 0], plain[:, -1]])
        self.assertGreater(border.max(), 12)

    def test_strong_is_darker_near_the_edges_than_soft(self):
        soft, strong = self.frame("soft"), self.frame("strong")
        ring = np.ones(soft.shape[:2], bool)
        ring[20:-20, 30:-30] = False
        self.assertLess(strong[ring].mean(), soft[ring].mean())
