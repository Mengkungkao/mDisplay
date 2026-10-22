#!/usr/bin/env python3
"""Generate assets/icon.png (128x128): a small spiral galaxy on a rounded dark tile.

The icon is procedural, made with mDisplay's own galaxy generator, so it
carries no third-party licence. Run again after changing the generator.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.scenes.galaxy import galaxy_disk  # noqa: E402


def make(size: int = 128, seed: int = 11) -> Image.Image:
    big = size * 4
    disk = galaxy_disk(np.random.default_rng(seed), big, 2).astype(np.float32) / 255.0
    rgb, alpha = disk[..., :3], disk[..., 3:4]
    tile = np.zeros((big, big, 3), np.float32)
    yy = np.linspace(0, 1, big, dtype=np.float32)[:, None]
    tile[...] = (np.array([8, 10, 26], np.float32) * (1 - yy[..., None]) +
                 np.array([20, 12, 40], np.float32) * yy[..., None]) / 255.0
    galaxy = Image.fromarray(np.clip((rgb * alpha * 1.6) * 255, 0, 255).astype(np.uint8))
    galaxy = galaxy.resize((big, int(big * 0.55)), Image.LANCZOS).rotate(-22, Image.BICUBIC, expand=False)
    canvas = Image.fromarray(np.clip(tile * 255, 0, 255).astype(np.uint8))
    offset = (0, (big - galaxy.height) // 2)
    base = np.asarray(canvas, np.float32)
    layer = np.zeros_like(base)
    layer[offset[1]:offset[1] + galaxy.height, :galaxy.width] = np.asarray(galaxy, np.float32)
    combined = np.clip(base + layer, 0, 255).astype(np.uint8)
    image = Image.fromarray(combined).filter(ImageFilter.GaussianBlur(0.6))
    image = image.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=size, fill=255)
    image.putalpha(mask.resize((size, size), Image.LANCZOS))
    return image


if __name__ == "__main__":
    path = os.path.join(ROOT, "assets", "icon.png")
    make().save(path)
    print(path)
