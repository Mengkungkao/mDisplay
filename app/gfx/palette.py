"""Colour helpers: star colours, smooth colour cycles, mixing."""

from __future__ import annotations

import math

import numpy as np


def kelvin(temperature: np.ndarray) -> np.ndarray:
    """Approximate blackbody colour (0..1 RGB) for 1000-40000 K (Tanner Helland's fit)."""
    t = np.clip(np.asarray(temperature, np.float64), 1000, 40000) / 100.0
    r = np.where(t <= 66, 255.0, 329.698727446 * np.power(np.maximum(t - 60, 1e-6), -0.1332047592))
    g = np.where(t <= 66, 99.4708025861 * np.log(t) - 161.1195681661,
                 288.1221695283 * np.power(np.maximum(t - 60, 1e-6), -0.0755148492))
    b = np.where(t >= 66, 255.0, np.where(t <= 19, 0.0,
                                          138.5177312231 * np.log(np.maximum(t - 10, 1e-6))
                                          - 305.0447927307))
    return np.clip(np.stack([r, g, b], axis=-1) / 255.0, 0, 1)


def star_colors(rng: np.random.Generator, n: int, saturation: float = 0.55,
                warm: float = 0.5) -> np.ndarray:
    """(n, 3) uint8 star tints: mostly white, some blue, some yellow-orange, a few red.

    ``warm`` shifts the mix towards K/M stars (0..1). The tint is mixed
    with white by (1 - saturation): stars look white with a hint of colour.
    """
    pick = rng.random(n)
    cool = 0.25 * (1.0 - warm)
    temps = np.where(pick < cool, rng.uniform(9500, 25000, n),
                     np.where(pick < cool + 0.40, rng.uniform(6200, 9500, n),
                              np.where(pick < 0.92, rng.uniform(4200, 6200, n),
                                       rng.uniform(2800, 4200, n))))
    rgb = kelvin(temps)
    rgb = rgb / np.maximum(rgb.max(axis=1, keepdims=True), 1e-6)
    rgb = 1.0 - saturation + saturation * rgb
    return np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def mix(a, b, t: float) -> tuple:
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


class Cycle:
    """A closed loop of colours sampled smoothly: ``at(phase)`` for any phase (1.0 = one loop)."""

    def __init__(self, colors: list):
        self.colors = [tuple(float(c) for c in color) for color in colors]

    def at(self, phase: float) -> tuple:
        n = len(self.colors)
        position = (phase % 1.0) * n
        i = int(math.floor(position)) % n
        f = position - math.floor(position)
        f = 0.5 - 0.5 * math.cos(math.pi * f)
        return mix(self.colors[i], self.colors[(i + 1) % n], f)


# Nebula gases, slowly: blue -> cyan -> violet -> pink -> red -> violet.
NEBULA = Cycle([(40, 80, 230), (20, 170, 220), (120, 70, 230), (225, 80, 170), (220, 60, 70),
                (150, 60, 200)])
