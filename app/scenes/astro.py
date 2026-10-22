"""Approximate heliocentric positions of the planets for a date.

Algorithm and elements: E. M. Standish (JPL), "Keplerian Elements for
Approximate Positions of the Major Planets", Table 1 (valid 1800-2050 AD):
mean orbital elements at J2000 plus linear rates per Julian century, then
Kepler's equation. The stated accuracy for this table is a few arcminutes
for the inner planets and up to about a degree for the outer ones.

The solar-system scene uses this only to *start* the planets where they
really are around today; from then on the motion is sped up and purely
illustrative, and the scene says so.
"""

from __future__ import annotations

import math
import time
from typing import NamedTuple


class Elements(NamedTuple):
    a: float           # semi-major axis, au
    e: float           # eccentricity
    i: float           # inclination, degrees
    L: float           # mean longitude, degrees
    peri: float        # longitude of perihelion, degrees
    node: float        # longitude of the ascending node, degrees


# (J2000 value, rate per Julian century)
ELEMENTS = {
    "mercury": (Elements(0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
                Elements(0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    "venus": (Elements(0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
              Elements(0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "earth": (Elements(1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              Elements(0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "mars": (Elements(1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             Elements(0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "jupiter": (Elements(5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                Elements(-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "saturn": (Elements(9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
               Elements(-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
    "uranus": (Elements(19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
               Elements(-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589)),
    "neptune": (Elements(30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
                Elements(0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664)),
}

PLANETS = tuple(ELEMENTS)
VALID_YEARS = (1800, 2050)


def julian_date(unix_seconds: float) -> float:
    return unix_seconds / 86400.0 + 2440587.5


def heliocentric(planet: str, unix_seconds: float) -> tuple:
    """(x, y, z) in au, J2000 ecliptic, for ``planet`` at a Unix time."""
    base, rate = ELEMENTS[planet]
    T = (julian_date(unix_seconds) - 2451545.0) / 36525.0
    a, e, i, L, peri, node = (b + r * T for b, r in zip(base, rate))
    omega = peri - node
    M = (L - peri + 180.0) % 360.0 - 180.0
    e_deg = math.degrees(e)
    E = M + e_deg * math.sin(math.radians(M))
    for _ in range(30):
        dM = M - (E - e_deg * math.sin(math.radians(E)))
        dE = dM / (1.0 - e * math.cos(math.radians(E)))
        E += dE
        if abs(dE) < 1e-7:
            break
    Er = math.radians(E)
    xp = a * (math.cos(Er) - e)
    yp = a * math.sqrt(1.0 - e * e) * math.sin(Er)
    w, O, I = math.radians(omega), math.radians(node), math.radians(i)
    x = ((math.cos(w) * math.cos(O) - math.sin(w) * math.sin(O) * math.cos(I)) * xp
         + (-math.sin(w) * math.cos(O) - math.cos(w) * math.sin(O) * math.cos(I)) * yp)
    y = ((math.cos(w) * math.sin(O) + math.sin(w) * math.cos(O) * math.cos(I)) * xp
         + (-math.sin(w) * math.sin(O) + math.cos(w) * math.cos(O) * math.cos(I)) * yp)
    z = (math.sin(w) * math.sin(I)) * xp + (math.cos(w) * math.sin(I)) * yp
    return x, y, z


def longitude(planet: str, unix_seconds: float) -> float:
    """Heliocentric ecliptic longitude in degrees, 0..360."""
    x, y, _ = heliocentric(planet, unix_seconds)
    return math.degrees(math.atan2(y, x)) % 360.0


def in_valid_range(unix_seconds: float) -> bool:
    year = time.gmtime(unix_seconds).tm_year
    return VALID_YEARS[0] <= year <= VALID_YEARS[1]
