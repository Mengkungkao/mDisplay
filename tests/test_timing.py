"""Animation time is real time x speed, frozen while paused, never jumping."""

import unittest

import helpers
from app.timing import AnimationClock, FramePacer, FrameStats


class ClockTests(unittest.TestCase):
    def test_scene_time_follows_real_time_and_speed(self):
        clock = helpers.FakeClock()
        anim = AnimationClock(clock)
        clock.advance(0.05)
        real, dt = anim.tick()
        self.assertAlmostEqual(real, 0.05)
        self.assertAlmostEqual(dt, 0.05)
        anim.speed = 2.0
        clock.advance(0.05)
        real, dt = anim.tick()
        self.assertAlmostEqual(dt, 0.1)
        self.assertAlmostEqual(anim.t, 0.15)

    def test_paused_time_does_not_advance(self):
        clock = helpers.FakeClock()
        anim = AnimationClock(clock)
        anim.paused = True
        clock.advance(5.0)
        self.assertEqual(anim.tick()[1], 0.0)
        self.assertEqual(anim.t, 0.0)

    def test_a_stall_is_capped_not_replayed(self):
        clock = helpers.FakeClock()
        anim = AnimationClock(clock, max_step=0.1)
        clock.advance(3.0)
        real, dt = anim.tick()
        self.assertEqual(real, 3.0)
        self.assertEqual(dt, 0.1)

    def test_resync_forgets_hidden_time(self):
        clock = helpers.FakeClock()
        anim = AnimationClock(clock)
        clock.advance(60.0)
        anim.resync()
        clock.advance(0.02)
        self.assertAlmostEqual(anim.tick()[1], 0.02)

    def test_frame_rate_does_not_change_animation_speed(self):
        results = []
        for fps in (24, 60, 144):
            clock = helpers.FakeClock()
            anim = AnimationClock(clock)
            for _ in range(fps * 10):
                clock.advance(1.0 / fps)
                anim.tick()
            results.append(anim.t)
        for value in results:
            self.assertAlmostEqual(value, 10.0, places=6)


class PacerTests(unittest.TestCase):
    def test_deadlines_follow_the_rate(self):
        clock = helpers.FakeClock()
        pacer = FramePacer(50, clock)
        self.assertEqual(pacer.remaining(), 0.0)
        pacer.frame_done()
        self.assertAlmostEqual(pacer.remaining(), 0.02)
        clock.advance(0.015)
        self.assertAlmostEqual(pacer.remaining(), 0.005)

    def test_falling_far_behind_restarts_instead_of_bursting(self):
        clock = helpers.FakeClock()
        pacer = FramePacer(60, clock)
        clock.advance(2.0)                 # a long stall
        pacer.frame_done()
        self.assertEqual(pacer.remaining(), 0.0)        # the next frame at once...
        pacer.frame_done()
        self.assertAlmostEqual(pacer.remaining(), 1 / 60)   # ...then the normal rate, no burst

    def test_a_slow_frame_does_not_add_a_wait(self):
        # Regression (Orange Pi, software): frames taking 70 ms at a 30 fps cap took
        # 104 ms because the pacer then waited a further full interval.
        clock = helpers.FakeClock()
        pacer = FramePacer(30, clock)
        for _ in range(5):
            clock.advance(0.070)           # drawing takes longer than the interval
            pacer.frame_done()
            self.assertEqual(pacer.remaining(), 0.0)

    def test_rate_changes(self):
        pacer = FramePacer(60, helpers.FakeClock())
        pacer.set_fps(20)
        self.assertAlmostEqual(pacer.interval, 0.05)
        pacer.set_fps(0)
        self.assertEqual(pacer.fps, 1.0)


class StatsTests(unittest.TestCase):
    def test_summary(self):
        stats = FrameStats(window=100)
        for _ in range(90):
            stats.add(1 / 60, 0.004)
        for _ in range(10):
            stats.add(0.05, 0.03)
        s = stats.summary()
        self.assertEqual(s["frames"], 100)
        self.assertAlmostEqual(s["frame_ms_p50"], 1000 / 60, places=3)
        self.assertAlmostEqual(s["frame_ms_max"], 50.0)
        self.assertGreater(s["fps"], 40)
        self.assertEqual(FrameStats().summary()["fps"], 0.0)


if __name__ == "__main__":
    unittest.main()
