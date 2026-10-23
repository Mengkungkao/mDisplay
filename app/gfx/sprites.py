"""Small textures generated once: star points, glows, meteor streaks, discs.

Each function returns an (H, W, 4) uint8 RGBA array (white, shaped by
alpha) that scenes tint per draw or per vertex.
"""

from __future__ import annotations

import numpy as np


def _radius(size: int) -> np.ndarray:
    c = (size - 1) / 2.0
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    return np.hypot(x - c, y - c) / np.float32(size / 2.0)


def white(alpha: np.ndarray, rgb=(255, 255, 255)) -> np.ndarray:
    out = np.empty(alpha.shape + (4,), np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def rgba(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Float RGB 0..1 (H, W, 3) and alpha 0..1 (H, W) -> uint8 RGBA."""
    out = np.empty(alpha.shape + (4,), np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def edge_fade(r: np.ndarray, start: float = 0.82) -> np.ndarray:
    """1 inside ``start``, smoothly 0 at the sprite's edge (no visible square)."""
    t = np.clip((1.0 - r) / (1.0 - start), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def star(size: int = 32, sigma: float = 0.16, halo: float = 0.10) -> np.ndarray:
    """A point of light: a Gaussian core with a faint wide halo."""
    r = _radius(size)
    core = np.exp(-(r * r) / (2 * sigma * sigma))
    wide = halo * np.exp(-(r * r) / (2 * (3.2 * sigma) ** 2))
    return white(np.clip(core + wide, 0, 1) * edge_fade(r))


def spiked_star(size: int = 96, sigma: float = 0.05) -> np.ndarray:
    """A bright star with soft four-point diffraction spikes."""
    c = (size - 1) / 2.0
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (x - c) / (size / 2.0), (y - c) / (size / 2.0)
    r = np.hypot(dx, dy)
    core = np.exp(-(r * r) / (2 * sigma * sigma)) + 0.18 * np.exp(-(r * r) / (2 * (3 * sigma) ** 2))
    width = 0.012
    along_x = np.exp(-(dy * dy) / (2 * width * width)) * np.clip(1 - np.abs(dx), 0, 1) ** 3
    along_y = np.exp(-(dx * dx) / (2 * width * width)) * np.clip(1 - np.abs(dy), 0, 1) ** 3
    alpha = np.clip(core + 0.55 * (along_x + along_y), 0, 1) * edge_fade(r, 0.9)
    return white(alpha)


def glow(size: int = 256, power: float = 2.4, core: float = 0.0) -> np.ndarray:
    """A soft radial glow; ``core`` adds a sharper centre."""
    r = np.clip(_radius(size), 0, 1)
    alpha = (1.0 - r) ** power
    if core:
        alpha = alpha + core * (1.0 - r) ** 2 / (1.0 + (r / 0.06) ** 2)
    return white(np.clip(alpha, 0, 1))


def disc(size: int = 128, softness: float = 1.5) -> np.ndarray:
    """An anti-aliased filled circle (``softness`` in pixels)."""
    c = (size - 1) / 2.0
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.hypot(x - c, y - c)
    radius = size / 2.0 - softness - 0.5
    return white(np.clip((radius - d) / softness + 0.5, 0, 1))


def streak(width: int = 256, height: int = 16) -> np.ndarray:
    """A meteor trail along x: faint thin tail (x=0) to a bright head (x=width-1)."""
    t = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    yy = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    body = t ** 2.4
    sigma = 0.10 + 0.32 * t
    across = np.exp(-(yy * yy) / (2 * sigma * sigma))
    head = np.exp(-((t - 0.985) ** 2) / (2 * 0.012 ** 2)) * np.exp(-(yy * yy) / (2 * 0.3 ** 2))
    alpha = np.clip(body * across + 0.9 * head, 0, 1)
    # Fade the very end so the head has no hard edge.
    alpha *= np.clip((1.0 - t) / 0.01, 0, 1) * 0.5 + 0.5
    return white(alpha)


def vertical_gradient(height: int, stops: list, width: int = 4) -> np.ndarray:
    """A (height, width) RGBA gradient; ``stops`` = [(position 0..1, (r, g, b, a))]."""
    pos = np.array([p for p, _ in stops], np.float32)
    cols = np.array([c for _, c in stops], np.float32)
    t = np.linspace(0.0, 1.0, height, dtype=np.float32)
    channels = [np.interp(t, pos, cols[:, k]) for k in range(4)]
    column = np.stack(channels, axis=-1)
    return np.clip(np.repeat(column[:, None, :], width, axis=1) + 0.5, 0, 255).astype(np.uint8)


EDGE_WIDTHS = {"soft": 0.07, "strong": 0.2}


def screen_edges(width: int, height: int, mode: str, size: int = 384) -> np.ndarray:
    """A multiply layer that fades the picture to black at the screen's border.

    White (no change) in the middle, smoothly black at every edge and darker
    still in the corners, so in a dark room the picture seems to float with no
    visible rectangle, like projected light. ``mode``: soft | strong.
    Small (``size`` on the long side) and scaled up: it is smooth anyway.
    """
    band = EDGE_WIDTHS.get(mode, EDGE_WIDTHS["soft"])
    if width >= height:
        tw, th = size, max(8, int(round(size * height / max(1, width))))
    else:
        tw, th = max(8, int(round(size * width / max(1, height)))), size
    short = min(width, height)
    x = (np.arange(tw, dtype=np.float32) + 0.5) / tw * width
    y = (np.arange(th, dtype=np.float32) + 0.5) / th * height
    dx = np.minimum(x, width - x) / short
    dy = np.minimum(y, height - y) / short
    # Distance to the border measured from texel centres; the outermost texels are 0.
    dx = np.clip((dx - dx.min()) / band, 0, 1)
    dy = np.clip((dy - dy.min()) / band, 0, 1)
    fx = dx * dx * (3 - 2 * dx)
    fy = dy * dy * (3 - 2 * dy)
    value = fy[:, None] * fx[None, :]
    if mode == "strong":
        # A gentle fall-off towards the edges as well, like a lamp's light cone.
        cx = (x / width - 0.5)[None, :] * 2
        cy = (y / height - 0.5)[:, None] * 2
        value = value * (1.0 - 0.3 * np.clip(cx * cx + cy * cy, 0, 2) / 2)
    image = np.empty((th, tw, 4), np.uint8)
    image[..., :3] = np.clip(value * 255.0 + 0.5, 0, 255).astype(np.uint8)[..., None]
    image[..., 3] = 255
    return image
