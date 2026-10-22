"""Procedural noise with NumPy: tileable gradient noise, fBm and domain warping.

Everything is vectorised (no per-pixel Python loops) and seeded, so the same
seed gives the same texture on every machine. Periods are whole lattice
cells, which makes each field tile seamlessly: a nebula or cloud layer can
drift forever without a visible seam.
"""

from __future__ import annotations

import numpy as np


def fade(t: np.ndarray) -> np.ndarray:
    """Quintic smoothstep 6t^5 - 15t^4 + 10t^3 (continuous 2nd derivative)."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


class Gradient2D:
    """Perlin-style gradient noise on a periodic lattice; ``sample`` returns about -1..1."""

    def __init__(self, rng: np.random.Generator, period_x: int, period_y: int):
        self.px = max(1, int(period_x))
        self.py = max(1, int(period_y))
        angles = rng.random((self.py, self.px), dtype=np.float32) * np.float32(2 * np.pi)
        self.gx = np.cos(angles).astype(np.float32)
        self.gy = np.sin(angles).astype(np.float32)

    def sample(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        u = np.asarray(u, np.float32)
        v = np.asarray(v, np.float32)
        u0 = np.floor(u)
        v0 = np.floor(v)
        fu = u - u0
        fv = v - v0
        x0 = u0.astype(np.int64) % self.px
        y0 = v0.astype(np.int64) % self.py
        x1 = (x0 + 1) % self.px
        y1 = (y0 + 1) % self.py
        gx, gy = self.gx, self.gy
        n00 = gx[y0, x0] * fu + gy[y0, x0] * fv
        n10 = gx[y0, x1] * (fu - 1.0) + gy[y0, x1] * fv
        n01 = gx[y1, x0] * fu + gy[y1, x0] * (fv - 1.0)
        n11 = gx[y1, x1] * (fu - 1.0) + gy[y1, x1] * (fv - 1.0)
        su = fade(fu)
        sv = fade(fv)
        top = n00 + (n10 - n00) * su
        bottom = n01 + (n11 - n01) * su
        return (top + (bottom - top) * sv) * np.float32(1.414)


class FBM:
    """Fractal sum of gradient noise; coordinates are in base-octave lattice cells."""

    def __init__(self, rng: np.random.Generator, period_x: int, period_y: int, octaves: int = 5,
                 gain: float = 0.5):
        self.octaves = [Gradient2D(rng, period_x * 2 ** k, period_y * 2 ** k)
                        for k in range(max(1, int(octaves)))]
        self.gain = float(gain)
        amplitudes = [self.gain ** k for k in range(len(self.octaves))]
        self._norm = 1.0 / sum(amplitudes)
        self._amplitudes = amplitudes

    def at(self, u: np.ndarray, v: np.ndarray, ridged: bool = False) -> np.ndarray:
        total = np.zeros(np.broadcast(u, v).shape, np.float32)
        for k, (octave, amplitude) in enumerate(zip(self.octaves, self._amplitudes)):
            n = octave.sample(u * (2 ** k), v * (2 ** k))
            if ridged:
                n = 1.0 - np.abs(n)
                n = n * n
            total += np.float32(amplitude) * n
        return total * np.float32(self._norm)


def grid(width: int, height: int, period_x: float, period_y: float) -> tuple:
    """Lattice coordinates (u, v) for an image of width x height spanning the periods."""
    u = (np.arange(width, dtype=np.float32) + 0.5) * np.float32(period_x / width)
    v = (np.arange(height, dtype=np.float32) + 0.5) * np.float32(period_y / height)
    return np.broadcast_to(u[None, :], (height, width)), np.broadcast_to(v[:, None], (height, width))


def periods(width: int, height: int, cells_across: int) -> tuple:
    """Whole-cell periods with square cells for a width x height tile."""
    px = max(1, int(round(cells_across)))
    py = max(1, int(round(cells_across * height / max(1, width))))
    return px, py


def fbm_image(rng: np.random.Generator, width: int, height: int, cells_across: int = 4,
              octaves: int = 5, gain: float = 0.5, ridged: bool = False) -> np.ndarray:
    """A tileable (height, width) fBm field in about 0..1."""
    px, py = periods(width, height, cells_across)
    field = FBM(rng, px, py, octaves, gain)
    u, v = grid(width, height, px, py)
    n = field.at(u, v, ridged)
    return n if ridged else n * np.float32(0.5) + np.float32(0.5)


def warped_image(rng: np.random.Generator, width: int, height: int, cells_across: int = 3,
                 octaves: int = 5, warp: float = 1.6, gain: float = 0.5) -> np.ndarray:
    """Domain-warped fBm: n(p + warp * (q(p), r(p))). Organic, gas-like; tileable; about 0..1."""
    px, py = periods(width, height, cells_across)
    u, v = grid(width, height, px, py)
    q_field = FBM(rng, px, py, max(2, octaves - 2), gain)
    r_field = FBM(rng, px, py, max(2, octaves - 2), gain)
    main = FBM(rng, px, py, octaves, gain)
    q = q_field.at(u, v)
    r = r_field.at(u + np.float32(5.2), v + np.float32(1.3))
    n = main.at(u + np.float32(warp) * q, v + np.float32(warp) * r)
    return n * np.float32(0.5) + np.float32(0.5)


class Noise1D:
    """Smooth periodic 1-D noise evolving in time: ``at(x, t)`` for arrays x in 0..1."""

    def __init__(self, rng: np.random.Generator, cells: int = 8, octaves: int = 3,
                 time_cells: int = 64):
        self.field = FBM(rng, cells, time_cells, octaves)
        self.time_cells = time_cells

    def at(self, x: np.ndarray, t: float) -> np.ndarray:
        cells = self.field.octaves[0].px
        x = np.asarray(x, np.float32) * np.float32(cells)
        return self.field.at(x, np.full_like(x, np.float32(t)))


def contrast(field: np.ndarray, low: float, high: float) -> np.ndarray:
    """Map [low, high] to [0, 1] with smooth ends."""
    t = np.clip((field - np.float32(low)) / np.float32(max(1e-6, high - low)), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)
