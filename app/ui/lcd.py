"""The Whisplay LCD screens (240x280) of mDisplay's remote control.

Pure functions from state to a Pillow image, in mFruit OS's look (SDK
chrome: status bar, lists, footer hints), so they can be rendered and
checked without a device. ``remote.py`` decides which screen shows and
feeds it the state.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from mfruit_sdk.ui import Canvas, Row, draw_list, footer, message, status_bar, toast
from mfruit_sdk.ui.theme import CONTENT_BOTTOM, CONTENT_TOP, MARGIN, SCREEN_W

from ..controls import Item
from ..scenes import catalog

THUMB_W, THUMB_H = 212, 119

# One table per screen: (gesture label, what it does). The remote's handlers
# implement exactly these; the footer shows as many as fit, in this order.
HOME_HINTS = [("tap", "next"), ("hold", "scenes"), ("3×", "pause"), ("2×", "previous"),
              ("4×", "exit")]
SCENES_HINTS = [("tap", "next"), ("hold", "show"), ("4×", "back"), ("3×", "pause"),
                ("2×", "previous")]
MENU_HINTS = [("tap", "next"), ("hold", "change"), ("4×", "back"), ("3×", "reverse"),
              ("2×", "previous")]
LIST_HINTS = [("tap", "next"), ("hold", "open"), ("4×", "back"), ("2×", "previous")]
DETAILS_HINTS = [("tap", "scroll"), ("4×", "back"), ("hold", "back")]


def _rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image.convert("RGB"), (0, 0), mask)
    return out


def _hints(table: list, armed: bool, release: str) -> list:
    return [("release", release)] if armed else list(table)


def home(state: dict, status=None, thumbnail=None, armed: bool = False, note: str = "") -> Image.Image:
    """Now showing: a thumbnail of the HDMI screen, the scene, what happens next."""
    c = Canvas()
    t = c.theme
    status_bar(c, "mDisplay", status)
    scene_id = state.get("scene") or "galaxy"
    x0 = (SCREEN_W - THUMB_W) // 2
    y0 = CONTENT_TOP + 6
    if thumbnail is not None:
        thumb = _rounded(thumbnail.resize((THUMB_W, THUMB_H)), 12)
        c.image.paste(thumb, (x0, y0), thumb)
    else:
        c.rounded((x0, y0, x0 + THUMB_W, y0 + THUMB_H), 12, fill=t.surface)
        c.text(SCREEN_W // 2, y0 + THUMB_H // 2, "Loading…" if state.get("loading") else "HDMI",
               13, "medium", t.text_faint, anchor="mm")
    y = y0 + THUMB_H + 10
    index = catalog.SCENE_IDS.index(scene_id) + 1 if scene_id in catalog.SCENE_IDS else 0
    c.text(MARGIN, y, catalog.name(scene_id), 19, "bold", t.text, max_width=SCREEN_W - 2 * MARGIN - 40)
    c.text(SCREEN_W - MARGIN, y + 4, f"{index}/{len(catalog.SCENE_IDS)}", 12, "medium",
           t.text_faint, anchor="ra")
    y += 26
    line, tone = _activity(state)
    c.text(MARGIN, y, line, 13, "medium", t.warning if tone == "warning" else t.text_muted,
           max_width=SCREEN_W - 2 * MARGIN)
    y += 19
    if state.get("output"):
        c.text(MARGIN, y, state["output"], 12, "regular", t.text_faint, max_width=SCREEN_W - 2 * MARGIN)
    footer(c, _hints(HOME_HINTS, armed, "to choose a scene"))
    if note:
        toast(c, note)
    return c.image


def _activity(state: dict) -> tuple:
    if state.get("loading"):
        return "Loading the next scene…", ""
    if state.get("paused"):
        return "Paused", "warning"
    parts = []
    rotation = state.get("rotation_remaining")
    if rotation is not None:
        parts.append(f"next scene in {_minutes(rotation)}")
    sleep = state.get("sleep_remaining")
    if sleep is not None:
        parts.append(f"sleep in {_minutes(sleep)}")
    if not parts:
        return catalog.info(state["scene"]).description if state.get("scene") in catalog.SCENE_IDS \
            else "", ""
    text = " · ".join(parts)
    return text[0].upper() + text[1:], ""


def _minutes(seconds: float) -> str:
    minutes = int(seconds // 60) + (1 if seconds % 60 else 0)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def scene_rows(current: str) -> list:
    """Every scene (the one on the HDMI screen marked), then Settings and Back."""
    rows = [Row(info.name, subtitle=info.description, kind="action",
                mark="success" if info.id == current else None)
            for info in catalog.SCENES]
    return rows + [Row("Settings", kind="nav"), Row("Back", kind="back")]


def scenes(current: str, selected: int, status=None, armed: bool = False,
           note: str = "") -> Image.Image:
    """Choose any scene: hold on a row shows it on the HDMI screen."""
    c = Canvas()
    status_bar(c, "Scenes", status)
    draw_list(c, scene_rows(current), selected)
    footer(c, _hints(SCENES_HINTS, armed, "to show it"))
    if note:
        toast(c, note)
    return c.image


def rows_from_items(items: "list[Item]") -> list:
    rows = []
    for item in items:
        kind = {"danger": "danger", "back": "back"}.get(item.kind, "action")
        rows.append(Row(item.label, value=item.value or None, kind=kind, enabled=item.enabled,
                        subtitle=item.note or None))
    return rows


def menu(items: list, selected: int, status=None, armed: bool = False, note: str = "") -> Image.Image:
    """The settings list (the same rows as the HDMI panel) plus a Back row."""
    c = Canvas()
    status_bar(c, "Settings", status)
    rows = rows_from_items(items) + [Row("Back", kind="back")]
    draw_list(c, rows, selected)
    footer(c, _hints(MENU_HINTS, armed, "to change"))
    if note:
        toast(c, note)
    return c.image


def problem(heading: str, body: str, choices: list, selected: int, status=None,
            armed: bool = False) -> Image.Image:
    """An error with what to do: the explanation, then Retry / Details / Back."""
    c = Canvas()
    status_bar(c, "mDisplay", status)
    split = CONTENT_TOP + 104
    message(c, heading, body, "warning", top=CONTENT_TOP, bottom=split)
    draw_list(c, [Row(label, kind="back" if label == "Back" else "action") for label in choices],
              selected, top=split + 4, bottom=CONTENT_BOTTOM)
    footer(c, _hints(LIST_HINTS, armed, "to choose"))
    return c.image


def details(title: str, lines: list, first: int, status=None) -> Image.Image:
    """Diagnostic lines, scrolled by taps."""
    c = Canvas()
    t = c.theme
    status_bar(c, title, status)
    y = CONTENT_TOP + 4
    wrapped = []
    for line in lines:
        wrapped += c.wrap(line, 12, "regular", SCREEN_W - 2 * MARGIN, max_lines=6) or [""]
    for line in wrapped[first:first + 12]:
        c.text(MARGIN, y, line, 12, "regular", t.text_muted)
        y += 17
    footer(c, DETAILS_HINTS)
    return c.image


def confirm(heading: str, body: str, selected: int, status=None, armed: bool = False) -> Image.Image:
    c = Canvas()
    status_bar(c, "Settings", status)
    split = CONTENT_TOP + 104
    message(c, heading, body, "", top=CONTENT_TOP, bottom=split)
    draw_list(c, [Row("Reset", kind="danger"), Row("Cancel", kind="back")], selected,
              top=split + 4, bottom=CONTENT_BOTTOM)
    footer(c, _hints(LIST_HINTS, armed, "to choose"))
    return c.image


def starting(text: str = "Starting the HDMI screen…", status=None) -> Image.Image:
    c = Canvas()
    status_bar(c, "mDisplay", status)
    message(c, "mDisplay", text)
    return c.image

