"""Meteors stay occasional: a Poisson rate set by the frequency setting, a cap on
how many fly at once, a minimum gap, and none at all at frequency 0."""

import math
import unittest

import numpy as np

import helpers  # noqa: F401
from app.scenes.parts import Meteors


def simulate(meteors, seconds, frequency=1.0, step=1 / 30, size=(1920, 1080)):
    peak = 0
    for _ in range(int(seconds / step)):
        meteors.update(step, frequency, *size)
        peak = max(peak, len(meteors.active))
    return peak


class MeteorTests(unittest.TestCase):
    def test_rate_follows_the_frequency_setting(self):
        counts = []
        for frequency in (0.5, 1.0, 2.0):
            m = Meteors(np.random.default_rng(1), per_minute=6.0, max_active=10, min_gap=0.0)
            simulate(m, 600, frequency)
            counts.append(m.spawned)
        expected = [30, 60, 120]                  # 6/min x frequency x 10 min
        for count, mean in zip(counts, expected):
            self.assertLess(abs(count - mean), 4 * math.sqrt(mean) + 2, (counts, expected))

    def test_frequency_zero_means_none(self):
        m = Meteors(np.random.default_rng(2), per_minute=60.0)
        simulate(m, 300, 0.0)
        self.assertEqual(m.spawned, 0)

    def test_never_more_than_the_cap_at_once(self):
        m = Meteors(np.random.default_rng(3), per_minute=600.0, max_active=3, min_gap=0.0)
        peak = simulate(m, 120, 3.0)
        self.assertEqual(peak, 3)

    def test_minimum_gap_between_meteors(self):
        m = Meteors(np.random.default_rng(4), per_minute=600.0, max_active=10, min_gap=2.0)
        times, t, step = [], 0.0, 1 / 30
        for _ in range(int(120 / step)):
            before = m.spawned
            m.update(step, 1.0, 1920, 1080)
            t += step
            if m.spawned > before:
                times.append(t)
        gaps = np.diff(times)
        self.assertGreater(len(times), 20)
        self.assertGreaterEqual(gaps.min(), 2.0 - 1e-6)

    def test_rate_does_not_depend_on_frame_rate(self):
        counts = {}
        for fps in (20, 60, 144):
            m = Meteors(np.random.default_rng(5), per_minute=12.0, max_active=10, min_gap=0.0)
            simulate(m, 600, 1.0, step=1 / fps)
            counts[fps] = m.spawned
        for count in counts.values():
            self.assertLess(abs(count - 120), 4 * math.sqrt(120), counts)

    def test_trails_fade_in_and_out(self):
        m = Meteors(np.random.default_rng(7))
        meteor = m.spawn(1920, 1080)
        meteor.age = 0.0
        self.assertEqual(m.envelope(meteor), 0.0)
        meteor.age = meteor.life * 0.3
        self.assertEqual(m.envelope(meteor), 1.0)
        meteor.age = meteor.life * 0.999
        self.assertLess(m.envelope(meteor), 0.01)
        meteor.age = meteor.life * 0.7
        self.assertTrue(0.0 < m.envelope(meteor) < 1.0)

    def test_dead_meteors_are_removed(self):
        m = Meteors(np.random.default_rng(8), per_minute=0.0)
        meteor = m.spawn(1920, 1080)
        m.update(meteor.life + 0.01, 1.0, 1920, 1080)
        self.assertEqual(m.active, [])


if __name__ == "__main__":
    unittest.main()
