"""The solar-system scene's starting positions come from JPL's approximate planet
positions; checked against dated events that pin heliocentric longitudes."""

import calendar
import time
import unittest

import helpers  # noqa: F401
from app.scenes import astro


def at(text: str) -> float:
    return calendar.timegm(time.strptime(text, "%Y-%m-%d %H:%M"))


def angle_between(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class AstroTests(unittest.TestCase):
    def test_earth_at_the_2024_equinox_and_solstice(self):
        # The Sun's geocentric longitude is 0 at the March equinox (Earth's
        # heliocentric 180) and 90 at the June solstice (Earth's 270). The
        # J2000 frame differs from the equinox of date by ~0.34 degrees in 2024.
        self.assertLess(angle_between(astro.longitude("earth", at("2024-03-20 03:06")), 180.0), 0.6)
        self.assertLess(angle_between(astro.longitude("earth", at("2024-06-20 20:51")), 270.0), 0.6)

    def test_planets_line_up_with_earth_at_opposition(self):
        for planet, when in (("jupiter", "2023-11-03 05:00"), ("mars", "2025-01-16 02:32"),
                             ("saturn", "2024-09-08 04:00")):
            with self.subTest(planet=planet):
                t = at(when)
                self.assertLess(angle_between(astro.longitude(planet, t),
                                              astro.longitude("earth", t)), 1.0)

    def test_orbit_sizes(self):
        t = at("2026-01-01 00:00")
        for planet, (low, high) in (("mercury", (0.30, 0.47)), ("earth", (0.98, 1.02)),
                                    ("neptune", (29.7, 30.4))):
            x, y, z = astro.heliocentric(planet, t)
            self.assertTrue(low <= (x * x + y * y + z * z) ** 0.5 <= high, planet)

    def test_valid_range(self):
        self.assertTrue(astro.in_valid_range(at("2026-10-22 00:00")))
        self.assertFalse(astro.in_valid_range(at("2051-01-01 00:00")))


if __name__ == "__main__":
    unittest.main()
