"""What mDisplay draws over a scene on the HDMI screen: transient captions and
toasts, the optional frame-rate line, and the settings panel.

Nothing here is permanent: the ambient view stays free of UI unless the
user opens the panel or asks for the frame-rate line. Text is rendered with
Pillow once per change and uploaded as a texture.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

from mfruit_sdk.ui.theme import DARK

from ..controls import Item
from ..gfx.canvas import BLEND, Canvas
from ..scenes import catalog
from . import text as textlib

CAPTION_IN, CAPTION_HOLD, CAPTION_OUT = 1.2, 3.5, 1.8
TOAST_IN, TOAST_OUT = 0.25, 0.6


def _envelope(age: float, fade_in: float, hold: float, fade_out: float) -> float:
    if age < 0:
        return 0.0
    if age < fade_in:
        x = age / fade_in
    elif age < fade_in + hold:
        x = 1.0
    else:
        x = max(0.0, 1.0 - (age - fade_in - hold) / fade_out)
    return x * x * (3.0 - 2.0 * x)


class _Layer:
    """One overlay texture, replaced when its content changes."""

    def __init__(self):
        self.texture = None
        self.pixels: Optional[np.ndarray] = None
        self.key = None

    def set(self, key, pixels: Optional[np.ndarray]) -> None:
        if key != self.key:
            self.key = key
            self.pixels = pixels
            if self.texture is not None:
                self.texture.destroy()
                self.texture = None

    def get(self, canvas: Canvas):
        if self.texture is None and self.pixels is not None:
            self.texture = canvas.texture(self.pixels, BLEND, name="overlay")
        return self.texture

    def drop(self) -> None:
        if self.texture is not None:
            self.texture.destroy()
            self.texture = None


class Overlay:
    def __init__(self, now=time.monotonic):
        self.now = now
        self.caption = _Layer()
        self.caption_start = -1e9
        self.toast = _Layer()
        self.toast_start = -1e9
        self.toast_seconds = 0.0
        self.info = _Layer()
        self.info_enabled = False
        self.info_next = 0.0
        self.panel = _Layer()
        self.panel_visible = False
        self.panel_alpha = 0.0
        self.scale = 1.0

    # ---------------------------------------------------------- content
    def resized(self, width: int, height: int) -> None:
        scale = max(0.4, min(width, height * 16 / 9) / 1920.0)
        if abs(scale - self.scale) > 1e-3:
            self.scale = scale
            for layer in (self.caption, self.toast, self.info, self.panel):
                layer.set(("resized", time.time()), None)

    def show_caption(self, scene_id: str) -> None:
        info = catalog.info(scene_id)
        s = self.scale
        title = textlib.label(info.name, int(56 * s), "semibold", (244, 246, 250), shadow=int(6 * s))
        sub = textlib.label(info.description, int(24 * s), "regular", (176, 186, 204),
                            shadow=int(4 * s))
        w = max(title.shape[1], sub.shape[1])
        image = np.zeros((title.shape[0] + sub.shape[0], w, 4), np.uint8)
        image[:title.shape[0], :title.shape[1]] = title
        image[title.shape[0]:, :sub.shape[1]] = sub
        self.caption.set(("caption", scene_id, self.now()), image)
        self.caption_start = self.now()

    def show_toast(self, message: str, seconds: float = 2.6) -> None:
        s = self.scale
        size = int(24 * s)
        tw, _ = textlib.measure(message, size, "medium")
        w, h = int(tw + 56 * s), int(size * 2.3)
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=DARK.surface_hi + (232,),
                               outline=DARK.separator + (255,))
        face = textlib.font(size, "medium")
        box = face.getbbox(message)
        draw.text(((w - (box[2] - box[0])) / 2 - box[0], (h - (box[3] - box[1])) / 2 - box[1]),
                  message, font=face, fill=DARK.text + (255,))
        self.toast.set(("toast", message, self.now()), textlib.to_rgba(image))
        self.toast_start = self.now()
        self.toast_seconds = seconds

    def set_info(self, enabled: bool) -> None:
        self.info_enabled = enabled
        self.info_next = 0.0
        if not enabled:
            self.info.set(None, None)

    def update_info(self, lines: list) -> None:
        if not self.info_enabled:
            return
        s = self.scale
        size = int(19 * s)
        rendered = [textlib.label(line, size, "medium", (210, 220, 236), shadow=int(3 * s))
                    for line in lines]
        w = max(r.shape[1] for r in rendered)
        h = sum(r.shape[0] for r in rendered)
        image = np.zeros((h, w, 4), np.uint8)
        y = 0
        for r in rendered:
            image[y:y + r.shape[0], :r.shape[1]] = r
            y += r.shape[0]
        self.info.set(("info", tuple(lines)), image)

    def show_panel(self, visible: bool) -> None:
        self.panel_visible = visible

    def set_panel(self, items: list, selected: int, hints: list, title: str, width: int,
                  height: int) -> None:
        self.panel.set(("panel", tuple((i.key, i.label, i.value, i.enabled, i.kind) for i in items),
                        selected, tuple(hints), title, width, height, self.scale),
                       render_panel(items, selected, hints, title, width, height, self.scale))

    # ----------------------------------------------------------- frames
    def busy(self) -> bool:
        """True while something is fading (frames are needed even when paused)."""
        now = self.now()
        caption_age = now - self.caption_start
        toast_age = now - self.toast_start
        return (caption_age < CAPTION_IN + CAPTION_HOLD + CAPTION_OUT
                or toast_age < TOAST_IN + self.toast_seconds + TOAST_OUT
                or (self.panel_visible and self.panel_alpha < 1.0)
                or (not self.panel_visible and self.panel_alpha > 0.0)
                or self.info_enabled)

    def draw(self, canvas: Canvas, frame_seconds: float = 1 / 60) -> None:
        now = self.now()
        w, h = canvas.width, canvas.height
        s = self.scale
        margin = int(0.045 * h)
        a = _envelope(now - self.caption_start, CAPTION_IN, CAPTION_HOLD, CAPTION_OUT)
        if a > 0:
            tex = self.caption.get(canvas)
            if tex is not None:
                canvas.image(tex, margin, h - margin - tex.height, alpha=int(255 * a * 0.92))
        a = _envelope(now - self.toast_start, TOAST_IN, self.toast_seconds, TOAST_OUT)
        if a > 0:
            tex = self.toast.get(canvas)
            if tex is not None:
                canvas.image(tex, (w - tex.width) / 2, h - margin - tex.height - int(40 * s),
                             alpha=int(255 * a))
        if self.info_enabled:
            tex = self.info.get(canvas)
            if tex is not None:
                canvas.image(tex, margin * 0.6, margin * 0.5, alpha=235)
        step = min(1.0, frame_seconds / 0.18)
        self.panel_alpha = min(1.0, self.panel_alpha + step) if self.panel_visible \
            else max(0.0, self.panel_alpha - step)
        if self.panel_alpha > 0:
            tex = self.panel.get(canvas)
            if tex is not None:
                slide = (1.0 - self.panel_alpha) * 24 * s
                canvas.image(tex, w - tex.width - margin + slide, (h - tex.height) / 2,
                             alpha=int(255 * self.panel_alpha))

    def close(self) -> None:
        for layer in (self.caption, self.toast, self.info, self.panel):
            layer.drop()

    def lost_textures(self) -> None:
        """After a renderer reset: forget textures, keep the pixels to upload again."""
        for layer in (self.caption, self.toast, self.info, self.panel):
            layer.texture = None


def render_panel(items: list, selected: int, hints: list, title: str, width: int, height: int,
                 scale: float) -> np.ndarray:
    """The settings panel as RGBA: title, a scrolling list, the selected row's note, key hints."""
    s = scale
    pw = int(min(max(0.30 * width, 380 * s), 640 * s))
    ph = int(min(0.86 * height, 980 * s))
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(28 * s)
    draw.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=radius, fill=(12, 14, 20, 228),
                           outline=(58, 66, 84, 200), width=max(1, int(1.5 * s)))
    pad = int(26 * s)
    y = pad
    draw.text((pad, y), "mDisplay", font=textlib.font(int(30 * s), "bold"), fill=DARK.text + (255,))
    y += int(40 * s)
    draw.text((pad, y), title, font=textlib.font(int(18 * s), "regular"),
              fill=DARK.text_muted + (255,))
    y += int(36 * s)
    row_h = int(44 * s)
    footer_h = int(86 * s)
    visible = max(1, (ph - y - footer_h) // row_h)
    first = max(0, min(selected - visible // 2, len(items) - visible))
    label_font = textlib.font(int(20 * s), "medium")
    bold_font = textlib.font(int(20 * s), "semibold")
    value_font = textlib.font(int(19 * s), "regular")
    for index in range(first, min(len(items), first + visible)):
        item: Item = items[index]
        top = y + (index - first) * row_h
        is_sel = index == selected
        if is_sel:
            draw.rounded_rectangle((int(10 * s), top + 2, pw - int(10 * s), top + row_h - 2),
                                   radius=int(14 * s), fill=DARK.accent_dim + (255,))
        color = DARK.text if item.enabled else DARK.text_faint
        if item.kind == "danger":
            color = DARK.error
        face = bold_font if is_sel else label_font
        mid = top + row_h // 2
        draw.text((pad, mid), item.label, font=face, fill=color + (255,), anchor="lm")
        if item.value:
            value_color = DARK.accent_text if is_sel else DARK.text_muted
            if not item.enabled:
                value_color = DARK.text_faint
            shown = item.value
            limit = pw * 0.5
            while shown and draw.textlength(shown, font=value_font) > limit:
                shown = shown[:-2] + "…" if len(shown) > 2 else ""
            draw.text((pw - pad, mid), shown, font=value_font, fill=value_color + (255,),
                      anchor="rm")
    if len(items) > visible:
        track_top, track_bottom = y, y + visible * row_h
        bar = max(int(20 * s), int((track_bottom - track_top) * visible / len(items)))
        offset = int((track_bottom - track_top - bar) * first / max(1, len(items) - visible))
        x = pw - int(6 * s)
        draw.rounded_rectangle((x - 2, track_top + offset, x, track_top + offset + bar), radius=1,
                               fill=DARK.text_faint + (255,))
    note = items[selected].note if 0 <= selected < len(items) else ""
    fy = ph - footer_h
    draw.line((pad, fy, pw - pad, fy), fill=DARK.separator + (255,), width=max(1, int(s)))
    if note:
        draw.text((pad, fy + int(12 * s)), note, font=textlib.font(int(17 * s), "regular"),
                  fill=DARK.text_muted + (255,))
    hint_font = textlib.font(int(16 * s), "medium")
    x = pad
    hy = ph - int(32 * s)
    for key, action in hints:              # most important first; drop what does not fit
        key_w = draw.textlength(key, font=hint_font)
        width = key_w + int(6 * s) + draw.textlength(action, font=hint_font)
        if x + width > pw - pad:
            break
        draw.text((x, hy), key, font=hint_font, fill=DARK.accent + (255,))
        draw.text((x + key_w + int(6 * s), hy), action, font=hint_font,
                  fill=DARK.text_muted + (255,))
        x += width + int(16 * s)
    return textlib.to_rgba(image)
