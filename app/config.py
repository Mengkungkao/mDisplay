"""mDisplay's settings: schema, validation, defaults and safe persistence.

The file is JSON (``settings.json`` in the app's data directory, see
``paths.py``). Loading never fails: a missing file gives the defaults; an
unreadable or malformed one is kept beside it as evidence
(``settings.json.corrupt-<time>``) and the defaults are used; a wrong value
falls back to its default and is reported. Keys this version does not know
(written by a newer mDisplay) are kept and written back unchanged. Saving
writes a temporary file, syncs it and renames it over the old one, so a
crash or full disk never leaves a half-written file.

The canonical description of every key is docs/CONFIGURATION.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Callable, NamedTuple, Optional

from .scenes.catalog import RETIRED as RETIRED_SCENES, SCENE_IDS, name as scene_name

log = logging.getLogger("mdisplay.config")

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 256 * 1024
QUALITIES = ("auto", "eco", "balanced", "high", "ultra")
SLEEP_ACTIONS = ("minimal", "pause", "exit")
UNFOCUSED = ("keep", "reduce", "pause")
EDGE_FADES = ("off", "soft", "strong")
GALAXY_VIEWS = ("inside", "outside")
MOTION = ("auto", "full", "gentle")
_DISPLAY_KEY = re.compile(r"^[A-Za-z0-9 _.:#()+-]{1,64}$")


def _times(value: float) -> str:
    return ("%g" % value) + "×"


def _percent(value: float) -> str:
    return f"{int(round(value * 100))}%"


def _seconds(value: float) -> str:
    return "Cut" if value <= 0 else ("%g s" % value)


def _minutes(value: float) -> str:
    value = int(value)
    if value <= 0:
        return "Off"
    hours, minutes = divmod(value, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h" if not minutes else f"{hours} h {minutes:02d}"


def _meteors(value: float) -> str:
    return "Off" if value <= 0 else _times(value)


def _on_off(value: bool) -> str:
    return "On" if value else "Off"


class Setting(NamedTuple):
    key: str
    default: Any
    kind: str                      # choice | number | flag | text
    label: str
    options: tuple = ()            # values the controls step through
    low: float = 0.0
    high: float = 0.0
    text: Optional[Callable] = None

    def validate(self, value):
        """(ok, value): the value as stored, or (False, default)."""
        if self.kind == "flag":
            return (True, value) if isinstance(value, bool) else (False, self.default)
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False, self.default
            if value != value:      # NaN
                return False, self.default
            clamped = min(self.high, max(self.low, float(value)))
            return clamped == float(value), clamped
        if self.kind == "choice":
            return (True, value) if value in self.options else (False, self.default)
        if self.kind == "text":
            return (True, value) if isinstance(value, str) and _DISPLAY_KEY.match(value) \
                else (False, self.default)
        return False, self.default

    def describe(self, value) -> str:
        if self.text:
            return self.text(value)
        return str(value)


def _scene_text(value):
    return scene_name(value)


SCHEMA = (
    Setting("scene", "galaxy", "choice", "Scene", SCENE_IDS, text=_scene_text),
    Setting("auto_rotate", False, "flag", "Change scenes", text=_on_off),
    Setting("rotate_minutes", 10, "choice", "Change every", (1, 2, 5, 10, 15, 30, 60, 120),
            text=_minutes),
    Setting("transition_seconds", 3.0, "number", "Transition", (0, 1, 2, 3, 5, 8, 10), 0, 10,
            text=_seconds),
    Setting("speed", 1.0, "number", "Speed", (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0), 0.25, 3.0,
            text=_times),
    Setting("brightness", 0.85, "number", "Brightness",
            (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0), 0.2, 1.0, text=_percent),
    Setting("star_density", 1.0, "number", "Stars", (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
            0.25, 2.0, text=_percent),
    Setting("nebula_intensity", 1.0, "number", "Nebula glow", (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5),
            0.0, 1.5, text=_percent),
    Setting("meteor_frequency", 1.0, "number", "Meteors", (0.0, 0.5, 1.0, 1.5, 2.0, 3.0), 0.0, 3.0,
            text=_meteors),
    Setting("quality", "auto", "choice", "Quality", QUALITIES, text=lambda v: v.capitalize()),
    Setting("fullscreen", True, "flag", "Full screen", text=_on_off),
    Setting("display", "auto", "text", "Screen"),
    Setting("sleep_minutes", 0, "choice", "Sleep timer", (0, 15, 30, 45, 60, 90, 120, 180, 240),
            text=_minutes),
    Setting("sleep_action", "minimal", "choice", "When it ends", SLEEP_ACTIONS,
            text=lambda v: {"minimal": "Minimal scene", "pause": "Pause",
                            "exit": "Close mDisplay"}[v]),
    Setting("unfocused", "reduce", "choice", "In the background", UNFOCUSED,
            text=lambda v: {"keep": "Keep going", "reduce": "Slow down", "pause": "Pause"}[v]),
    Setting("motion", "auto", "choice", "Motion", MOTION,
            text=lambda v: {"auto": "Auto", "full": "Full", "gentle": "Gentle"}[v]),
    Setting("edge_fade", "soft", "choice", "Soft edges", EDGE_FADES,
            text=lambda v: v.capitalize()),
    Setting("galaxy_view", "inside", "choice", "Galaxy view", GALAXY_VIEWS,
            text=lambda v: v.capitalize()),
    Setting("show_scene_name", True, "flag", "Scene names", text=_on_off),
    Setting("clouds", True, "flag", "Clouds", text=_on_off),
    Setting("horizon", True, "flag", "Horizon", text=_on_off),
    Setting("mountains", True, "flag", "Mountains", text=_on_off),
    Setting("allow_screen_blanking", False, "flag", "Screen blanking", text=_on_off),
    Setting("vsync", "auto", "choice", "Vertical sync", ("auto", "on", "off"),
            text=lambda v: v.capitalize()),
)

SETTINGS = {setting.key: setting for setting in SCHEMA}
# Settings of removed scenes: dropped when a settings file is read.
RETIRED_KEYS = {"orbits", "planet_labels", "projector_colors", "projector_lasers",
                "projector_rotation"}
DEFAULTS = {setting.key: setting.default for setting in SCHEMA}


class Settings:
    """Validated values plus unknown keys kept for newer versions."""

    def __init__(self, values: Optional[dict] = None, extra: Optional[dict] = None):
        self.values = dict(DEFAULTS)
        self.extra = dict(extra or {})
        for key, value in (values or {}).items():
            self.values[key] = value

    def __getitem__(self, key: str):
        return self.values[key]

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value) -> bool:
        """Validate and store; True when the value changed. Raises ValueError if invalid."""
        setting = SETTINGS[key]
        ok, checked = setting.validate(value)
        if not ok and checked != value:
            raise ValueError(f"{key}: invalid value {value!r}")
        if self.values.get(key) == checked:
            return False
        self.values[key] = checked
        return True

    def step(self, key: str, direction: int = 1, wrap: bool = True, options: tuple = ()):
        """Move to the next (or previous) option; returns the new value."""
        setting = SETTINGS[key]
        if setting.kind == "flag":
            self.set(key, not self.values[key])
            return self.values[key]
        options = tuple(options or setting.options)
        if not options:
            return self.values[key]
        current = self.values[key]
        if current in options:
            index = options.index(current) + direction
        elif setting.kind == "number":
            # Not on the list (edited by hand): go to the nearest option that way.
            if direction > 0:
                index = next((i for i, v in enumerate(options) if v > current), len(options))
            else:
                index = next((i for i in range(len(options) - 1, -1, -1) if options[i] < current), -1)
        else:
            index = 0
        if wrap:
            index %= len(options)
        else:
            index = max(0, min(len(options) - 1, index))
        self.set(key, options[index])
        return self.values[key]

    def reset(self) -> set:
        changed = {key for key, value in DEFAULTS.items() if self.values.get(key) != value}
        self.values = dict(DEFAULTS)
        return changed

    def copy(self) -> "Settings":
        return Settings(self.values, self.extra)

    def as_dict(self) -> dict:
        data = dict(self.extra)
        data.update(self.values)
        data["schema"] = SCHEMA_VERSION
        return data

    def text(self, key: str) -> str:
        return SETTINGS[key].describe(self.values[key])


def parse(data: dict) -> tuple:
    """(Settings, problems) from a decoded file."""
    problems = []
    values, extra = {}, {}
    if not isinstance(data, dict):
        return Settings(), ["the settings file does not hold an object; defaults loaded"]
    schema = data.get("schema", SCHEMA_VERSION)
    if isinstance(schema, int) and schema > SCHEMA_VERSION:
        problems.append(f"settings were written by a newer mDisplay (schema {schema}); "
                        "unknown keys are kept")
    for key, value in data.items():
        if key == "schema":
            continue
        setting = SETTINGS.get(key)
        if setting is None:
            if key not in RETIRED_KEYS:
                extra[key] = value
            continue
        if key == "scene" and value in RETIRED_SCENES:
            value = RETIRED_SCENES[value]          # a removed scene: its replacement, quietly
        ok, checked = setting.validate(value)
        if not ok:
            if setting.kind == "number" and checked != setting.default:
                problems.append(f"{key}: {value!r} is out of range; using {checked:g}")
            else:
                problems.append(f"{key}: {value!r} is not valid; using the default "
                                f"{setting.default!r}")
        values[key] = checked
    return Settings(values, extra), problems


class SettingsStore:
    def __init__(self, path: str, clock: Callable[[], float] = time.time):
        self.path = path
        self.clock = clock
        self.last_error = ""

    def load(self) -> tuple:
        """(Settings, problems). Never raises."""
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return Settings(), []
        except OSError as exc:
            return Settings(), [f"cannot read {self.path}: {exc.strerror or exc}; defaults loaded"]
        try:
            if size > MAX_FILE_BYTES:
                raise ValueError(f"the file is too large ({size} bytes)")
            with open(self.path, "rb") as handle:
                data = json.loads(handle.read().decode("utf-8"))
        except PermissionError as exc:
            return Settings(), [f"cannot read {self.path}: {exc.strerror}; defaults loaded"]
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            kept = self._keep_corrupt()
            note = f" (kept as {os.path.basename(kept)})" if kept else ""
            return Settings(), [f"the settings file was unreadable ({exc}){note}; defaults loaded"]
        settings, problems = parse(data)
        return settings, problems

    def _keep_corrupt(self) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
        target = f"{self.path}.corrupt-{stamp}"
        try:
            os.replace(self.path, target)
            return target
        except OSError as exc:
            log.warning("could not keep the unreadable settings file: %s", exc)
            return ""

    def save(self, settings: Settings) -> bool:
        """Atomically write the settings; False (and ``last_error``) on failure."""
        directory = os.path.dirname(os.path.abspath(self.path))
        tmp = None
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(settings.as_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            tmp = None
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
            self.last_error = ""
            return True
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = f"cannot save settings: {getattr(exc, 'strerror', None) or exc}"
            log.warning("%s (%s)", self.last_error, self.path)
            return False
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
