"""Text and panels drawn with Pillow, in mFruit OS's fonts (Inter, else DejaVu)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from mfruit_sdk.ui import fonts as sdk_fonts


def font(size: int, weight: str = "regular"):
    return sdk_fonts.shared().get(max(6, int(size)), weight)


def measure(text: str, size: int, weight: str = "regular") -> tuple:
    box = font(size, weight).getbbox(text or " ")
    return box[2] - box[0], box[3] - box[1]


def label(text: str, size: int, weight: str = "regular", color=(240, 244, 250),
          shadow: int = 0, pad: int = 4) -> np.ndarray:
    """One line of text as straight-alpha RGBA, with an optional soft shadow."""
    face = font(size, weight)
    box = face.getbbox(text or " ")
    w = box[2] - box[0] + 2 * pad + 2 * shadow
    h = int(size * 1.35) + 2 * pad + 2 * shadow
    mask = Image.new("L", (max(1, w), max(1, h)), 0)
    ImageDraw.Draw(mask).text((pad + shadow - box[0], pad + shadow), text, font=face, fill=255)
    out = np.zeros((h, w, 4), np.uint8)
    if shadow:
        blurred = np.asarray(mask.filter(ImageFilter.GaussianBlur(shadow)), np.float32) * 0.7
        out[..., 3] = blurred.astype(np.uint8)
    glyph = np.asarray(mask, np.float32) / 255.0
    alpha = out[..., 3].astype(np.float32) / 255.0
    final = glyph + alpha * (1.0 - glyph)
    for k in range(3):
        out[..., k] = np.clip(color[k] * glyph / np.maximum(final, 1e-4), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(final * 255.0, 0, 255).astype(np.uint8)
    return out


def to_rgba(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), np.uint8).copy()
