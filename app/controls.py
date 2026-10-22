"""Commands, key bindings and the settings menu — one table each.

The same menu model drives the settings panel on the HDMI screen (when
mDisplay runs on its own) and the remote-control menu on the Whisplay LCD
(when mFruit OS runs it), so the two can never offer different controls.
Footer hints are generated from the binding tables, so a hint can never
advertise a key that does nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import SETTINGS, Settings
from .scenes import catalog

# Commands (the application's ``handle`` understands exactly these).
NEXT_SCENE = "next_scene"
PREV_SCENE = "prev_scene"
PAUSE = "pause"
FULLSCREEN = "fullscreen"
PANEL = "panel"
INFO = "info"
EXIT = "exit"
PANEL_NEXT = "panel_next"
PANEL_PREV = "panel_prev"
PANEL_INC = "panel_inc"
PANEL_DEC = "panel_dec"
PANEL_SELECT = "panel_select"
PANEL_CLOSE = "panel_close"

# Window keys while the scene is shown: (keys, command, what it does).
AMBIENT_KEYS = (
    (("right",), NEXT_SCENE, "next scene"),
    (("left",), PREV_SCENE, "previous scene"),
    (("space",), PAUSE, "pause"),
    (("f11", "f"), FULLSCREEN, "full screen"),
    (("b", "tab", "enter", "m"), PANEL, "settings"),
    (("i",), INFO, "frame rate"),
    (("escape", "q"), EXIT, "close"),
)

# Window keys while the settings panel is open.
PANEL_KEYS = (
    (("down", "tab"), PANEL_NEXT, "move"),
    (("up", "shift+tab"), PANEL_PREV, "move"),
    (("right",), PANEL_INC, "change"),
    (("left",), PANEL_DEC, "change"),
    (("enter", "space"), PANEL_SELECT, "select"),
    (("escape", "b"), PANEL_CLOSE, "close"),
    (("f11",), FULLSCREEN, "full screen"),
    (("q",), EXIT, "quit"),
)

KEY_LABELS = {"right": "→", "left": "←", "up": "↑", "down": "↓", "space": "Space",
              "enter": "Enter", "escape": "Esc", "tab": "Tab", "shift+tab": "Shift+Tab",
              "f11": "F11"}


def lookup(table, key: str) -> Optional[str]:
    for keys, command, _ in table:
        if key in keys:
            return command
    return None


def key_hints(table, keep: int = 99) -> list:
    """[(key label, action)] for footers, merging rows that share a description."""
    hints, seen = [], {}
    for keys, _command, description in table:
        label = KEY_LABELS.get(keys[0], keys[0].upper() if len(keys[0]) == 1 else keys[0])
        if description in seen:
            index = seen[description]
            hints[index] = (hints[index][0] + label, description)
            continue
        seen[description] = len(hints)
        hints.append((label, description))
    return hints[:keep]


# ------------------------------------------------------------------ menu

@dataclass
class Item:
    key: str
    label: str
    value: str = ""
    kind: str = "setting"        # setting | action | danger | back
    enabled: bool = True
    note: str = ""               # a second line (the LCD shows it as a subtitle)


QUALITY_NAMES = {"eco": "Eco", "balanced": "Balanced", "high": "High", "ultra": "Ultra"}

MENU_SETTINGS = ("scene", "auto_rotate", "rotate_minutes", "transition_seconds", "speed",
                 "motion", "brightness", "edge_fade", "star_density", "nebula_intensity", "meteor_frequency",
                 "projector_colors", "projector_lasers", "projector_rotation", "quality",
                 "fullscreen", "display", "sleep_minutes", "sleep_action", "show_scene_name",
                 "clouds", "horizon", "mountains", "unfocused",
                 "allow_screen_blanking")


def display_options(displays: list) -> tuple:
    return ("auto",) + tuple(info.key for info in displays)


def display_text(key: str, displays: list) -> str:
    if key == "auto":
        return "Automatic"
    for info in displays:
        if info.key == key:
            return info.label
    return f"{key} (not connected)"


def menu(settings: Settings, state: dict, standalone: bool = True, displays: list = ()) -> list:
    """The settings menu rows for the current state.

    ``state``: paused, quality (resolved name), sleep_remaining (s or None),
    confirm_reset (bool).
    """
    rows = [Item(PAUSE, "Resume" if state.get("paused") else "Pause", kind="action")]
    for key in MENU_SETTINGS:
        if key == "unfocused" and not standalone:
            continue                      # the window rarely has focus under mFruit OS
        setting = SETTINGS[key]
        value = settings.text(key)
        note = ""
        enabled = True
        if key == "quality":
            resolved = QUALITY_NAMES.get(state.get("quality", ""), "")
            if settings["quality"] == "auto" and resolved:
                value = f"Auto ({resolved})"
        elif key == "display":
            value = display_text(settings["display"], displays)
        elif key == "rotate_minutes":
            enabled = bool(settings["auto_rotate"])
        elif key == "sleep_minutes":
            remaining = state.get("sleep_remaining")
            if remaining is not None and settings["sleep_minutes"]:
                note = f"{int(remaining // 60) + 1} min left"
        elif key == "scene":
            note = catalog.info(settings["scene"]).description
        elif key == "motion":
            gentle = state.get("gentle")
            if settings["motion"] == "auto" and gentle is not None:
                value = "Auto (Gentle)" if gentle else "Auto (Full)"
            note = "Gentle: slower movement and soft fades, for boards without a GPU"
        rows.append(Item(key, setting.label, value, enabled=enabled, note=note))
    rows.append(Item("reset", "Press again to reset" if state.get("confirm_reset")
                     else "Reset to defaults", kind="danger"))
    rows.append(Item(EXIT, "Close mDisplay", kind="action"))
    return rows


def step_setting(settings: Settings, key: str, direction: int, displays: list = ()) -> bool:
    """Change a menu setting by one option; True when it changed."""
    before = settings[key]
    if key == "display":
        options = display_options(displays)
        current = settings["display"]
        index = options.index(current) if current in options else -1
        settings.set("display", options[(index + direction) % len(options)])
    elif key == "scene":
        settings.set("scene", catalog.neighbour(settings["scene"], direction))
    else:
        settings.step(key, direction, wrap=True)
    return settings[key] != before
