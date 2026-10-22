"""Gentle motion (the ``motion`` setting) and the software renderer's cached
drawing: slower movement and fades for boards that draw a few frames a second."""

import math
import unittest
from concurrent.futures import Future
from unittest import mock

import numpy as np

import helpers
from app.config import Settings
from app.scenes import catalog
from app.scenes import galaxy as galaxy_scene
from app.scenes import projector as projector_scene
from app.scenes.base import QUALITY, SceneContext, resolve_motion
from app.scenes import starlight
from app.scenes.parts import StarField


def run(off, scene_id, gentle, seconds=1.0, step=0.1):
    clock = helpers.FakeClock()
    settings = Settings()
    settings.set("transition_seconds", 0)
    engine = off.engine(settings, clock, gentle=gentle)
    engine.request(scene_id)
    off.frame(engine)
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        engine.update(step)
    return engine, clock


class ResolveMotionTests(unittest.TestCase):
    def test_auto_is_gentle_only_without_a_gpu(self):
        self.assertTrue(resolve_motion("auto", accelerated=False))
        self.assertFalse(resolve_motion("auto", accelerated=True))

    def test_explicit_choices_win(self):
        for accelerated in (False, True):
            self.assertTrue(resolve_motion("gentle", accelerated))
            self.assertFalse(resolve_motion("full", accelerated))


class GentlePartsTests(unittest.TestCase):
    def test_calm_stars_twinkle_slower_and_shallower(self):
        stars = StarField(np.random.default_rng(2), 50)
        f1, depth = stars.f1.copy(), stars.depth.copy()
        stars.calm()
        np.testing.assert_allclose(stars.f1, f1 * 0.35, rtol=1e-6)
        self.assertTrue((stars.depth < depth).all())


class GentleSceneTests(unittest.TestCase):
    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_every_scene_draws_and_moves_in_gentle_motion(self):
        baseline = self.off.canvas.live_textures
        for scene_id in catalog.SCENE_IDS:
            with self.subTest(scene=scene_id):
                engine, clock = run(self.off, scene_id, gentle=True)
                self.assertNotIn(scene_id, engine.failed)
                self.assertTrue((engine.current or engine.incoming).scene.gentle)
                first = self.off.frame(engine).astype(np.int16)
                self.assertGreater(first[..., :3].max(), 40, "nothing visible")
                for _ in range(40):
                    clock.advance(0.1)
                    engine.update(0.1)
                second = self.off.frame(engine).astype(np.int16)
                changed = (np.abs(first - second).max(axis=2) > 2).mean()
                self.assertGreater(changed, 0.0002, "the scene did not move in 4 s")
                engine.close()
                self.assertEqual(self.off.canvas.live_textures, baseline)

    def test_projector_turns_at_half_speed(self):
        angles = {}
        for gentle in (False, True):
            engine, _ = run(self.off, "projector", gentle)
            scene = (engine.current or engine.incoming).scene
            scene.t = 100.0
            angles[gentle] = scene.turn()
            engine.close()
        self.assertAlmostEqual(angles[True], angles[False] * projector_scene.GENTLE_TURN)
        self.assertGreater(angles[False], 0)


class StillSkyTests(unittest.TestCase):
    """Gentle motion: nothing travels across the sky; stars only fade and twinkle."""

    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_no_meteors_and_no_drift_in_gentle_motion(self):
        for scene_id in ("nightsky", "minimal"):
            with self.subTest(scene=scene_id):
                engine, clock = run(self.off, scene_id, gentle=True)
                scene = (engine.current or engine.incoming).scene
                self.assertIsNone(scene.meteors)
                stars = scene.stars
                before = stars.positions(320, 180, stars.n, 0.0, 0.0, wrap=True)
                for _ in range(100):                      # 10 s
                    clock.advance(0.1)
                    engine.update(0.1)
                self.off.frame(engine)
                after = stars.positions(320, 180, stars.n, 0.0, 0.0, wrap=True)
                np.testing.assert_array_equal(before[0], after[0])
                engine.close()

    def test_full_motion_keeps_its_meteors(self):
        for scene_id in ("nightsky", "minimal"):
            with self.subTest(scene=scene_id):
                engine, _ = run(self.off, scene_id, gentle=False)
                self.assertIsNotNone((engine.current or engine.incoming).scene.meteors)
                engine.close()


class StarlightTests(unittest.TestCase):
    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_a_star_fades_in_holds_and_fades_out_smoothly(self):
        phase = np.linspace(0, 1, 2001)
        level = starlight.envelope(phase)
        self.assertEqual(level[0], 0.0)
        self.assertAlmostEqual(level.max(), 1.0)
        self.assertTrue((level[phase >= starlight.LIT] == 0).all())      # rests dark
        # Smooth: no step bigger than a slow fade's at 2000 samples a cycle.
        self.assertLess(np.abs(np.diff(level)).max(), 0.01)

    def test_nothing_moves_while_it_is_lit(self):
        engine, _ = run(self.off, "starlight", gentle=False)
        scene = (engine.current or engine.incoming).scene
        n = len(scene.period)
        moved_while_lit = 0
        relocated = 0
        x0, y0, l0 = scene.stars(100.0, n)
        for step in range(1, 400):
            x1, y1, l1 = scene.stars(100.0 + step * 0.1, n)
            both = (l0 > 0) & (l1 > 0)
            moved_while_lit += int(((x0 != x1) | (y0 != y1))[both].sum())
            relocated += int((x0 != x1).sum())
            x0, y0, l0 = x1, y1, l1
        self.assertEqual(moved_while_lit, 0)
        self.assertGreater(relocated, n // 4)             # stars come back elsewhere
        engine.close()

    def test_some_stars_are_always_shining(self):
        engine, clock = run(self.off, "starlight", gentle=False)
        scene = (engine.current or engine.incoming).scene
        n = len(scene.period)
        for t in (0.0, 7.3, 61.0, 600.0):
            _, _, level = scene.stars(t, n)
            self.assertGreater((level > 0.5).mean(), 0.3, t)
        engine.close()


class SoftwareGalaxyTests(unittest.TestCase):
    """The software renderer shows the tilted galaxy from images composed at whole
    steps (on the CPU, off the render thread) and blended, never turning it per frame."""

    def setUp(self):
        self.off = helpers.Offscreen(320, 180)

    def tearDown(self):
        self.off.close()

    def test_composes_once_per_step_not_every_frame(self):
        original = galaxy_scene.GalaxyScene.compose
        with mock.patch.object(galaxy_scene.GalaxyScene, "compose", autospec=True,
                               side_effect=original) as composed:
            engine, clock = run(self.off, "galaxy", gentle=False, seconds=0.1)
            scene = (engine.current or engine.incoming).scene
            steps = 3.5                                   # degrees the pattern turns
            seconds = galaxy_scene.TURN_SECONDS * steps / 360.0
            frames = 60
            for _ in range(frames):
                clock.advance(seconds / frames)
                engine.update(seconds / frames)
                self.off.frame(engine)
        # Two at the start, then one each time a step is passed.
        self.assertLessEqual(composed.call_count, 2 + math.ceil(steps / galaxy_scene.COMPOSE_STEP))
        self.assertLessEqual(len(scene.composite_tex), 2)
        engine.close()

    def test_the_composed_galaxy_matches_what_the_renderer_draws(self):
        engine, _ = run(self.off, "galaxy", gentle=False, seconds=0.1)
        scene = (engine.current or engine.incoming).scene
        canvas = self.off.canvas
        diameter, squash, (w, h) = scene.geometry()
        for step in (0, 37, 200):
            with self.subTest(step=step):
                reference = canvas.target(w, h, "reference")
                scene._turn_disk(canvas, step * galaxy_scene.COMPOSE_STEP)
                with canvas.into(reference):
                    canvas.clear((0, 0, 0), alpha=255)
                    canvas.centered(scene.frame, w / 2.0, h / 2.0, diameter, diameter * squash,
                                    galaxy_scene.TILT)
                    scene._draw_glows(canvas, w / 2.0, h / 2.0, diameter, squash, 1.0, 1.0)
                    drawn = canvas.read_rgba()[..., :3].astype(np.float32)
                reference.destroy()
                composed = scene.compose(step)[..., :3].astype(np.float32)
                self.assertEqual(composed.shape, drawn.shape)
                self.assertGreater(composed.max(), 100)
                # The same picture: a turn the wrong way or a mirrored tilt differs about
                # half the mean level; SDL's 8-bit blending makes its copy a little darker.
                level = drawn.mean()
                self.assertLess(np.abs(composed - drawn).mean(), 0.15 * level)
                self.assertLess(abs(composed.mean() - level), 0.12 * level)
        engine.close()

    def test_the_next_step_is_composed_in_the_background(self):
        submitted = []

        def background(fn, *args):
            submitted.append(args)
            future = Future()
            future.set_result(fn(*args))
            return future
        clock = helpers.FakeClock()
        settings = Settings()
        settings.set("transition_seconds", 0)
        engine = self.off.engine(settings, clock)
        make = engine.make_context

        def with_background():
            context = make()
            context.background = background
            return context
        engine.make_context = with_background
        engine.request("galaxy")
        self.off.frame(engine)
        self.assertIn((2,), submitted)
        engine.close()

    def test_blending_between_steps_has_no_jump(self):
        engine, clock = run(self.off, "galaxy", gentle=False, seconds=0.1)
        scene = (engine.current or engine.incoming).scene
        # Frames either side of a step boundary differ about as much as any two frames.
        boundary = galaxy_scene.TURN_SECONDS * galaxy_scene.COMPOSE_STEP / 360.0
        small = 0.02
        diffs = []
        for t in (boundary - 3 * small, boundary - 2 * small, boundary - small, boundary + small):
            engine.update(t - scene.t)
            diffs.append(self.off.frame(engine).astype(np.int16))
        steady = np.abs(diffs[1] - diffs[0]).mean()
        across = np.abs(diffs[3] - diffs[2]).mean()
        self.assertLess(across, steady + 0.5)
        engine.close()


if __name__ == "__main__":
    unittest.main()
