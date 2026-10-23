"""The package smoke test (``test.sh``): quick, offline, and never on a real screen.

1. imports every module;
2. settings: defaults, a malformed file, an atomic save and reload, in a
   temporary directory;
3. draws every Whisplay LCD screen with Pillow (nothing is sent to the LCD);
4. renders every scene for a few simulated frames at 320x180 with SDL's
   dummy video driver and software renderer (no window is shown) and checks
   that something was drawn.

Exit status 0 = pass; anything else keeps the previous version installed.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time

MODULES = ("app.main", "app.application", "app.config", "app.controls", "app.engine",
           "app.timing", "app.paths", "app.diagnostics", "app.remote", "app.whisplay",
           "app.display.sdl2", "app.display.session", "app.display.desktop", "app.gfx.canvas",
           "app.gfx.batch", "app.gfx.noise", "app.gfx.sprites", "app.gfx.palette",
           "app.ui.lcd", "app.ui.overlay", "app.ui.text", "app.scenes.catalog",
           "app.scenes.base", "app.scenes.parts")


def check_settings() -> None:
    from .config import Settings, SettingsStore
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "settings.json")
        store = SettingsStore(path)
        settings, problems = store.load()
        assert not problems and settings["scene"] == "galaxy", problems
        with open(path, "w") as handle:
            handle.write("{not json")
        settings, problems = store.load()
        assert problems and settings["speed"] == 1.0
        assert any(name.startswith("settings.json.corrupt-") for name in os.listdir(tmp))
        settings = Settings()
        settings.set("speed", 2.0)
        assert store.save(settings), store.last_error
        with open(path) as handle:
            assert json.load(handle)["speed"] == 2.0
        assert store.load()[0]["speed"] == 2.0


def check_lcd() -> int:
    from mfruit_sdk.status import Status

    from . import controls
    from .config import Settings
    from .ui import lcd
    status = Status(2, 80, False)
    items = controls.menu(Settings(), {"paused": False, "quality": "eco"}, standalone=False)
    images = [
        lcd.starting(status=status),
        lcd.home({"scene": "galaxy", "output": "HDMI-1 · 1920×1080", "rotation_remaining": 300.0},
                 status),
        lcd.home({"scene": "aurora", "paused": True}, status, armed=True, note="Paused"),
        lcd.scenes("nebula", 6, status),
        lcd.menu(items, 3, status),
        lcd.problem("No HDMI desktop", "Log in to the desktop on the HDMI screen.",
                    ["Retry", "Details", "Back"], 0, status),
        lcd.details("Details", ["line one", "line two"], 0, status),
        lcd.confirm("Reset settings?", "Everything goes back to its default.", 0, status),
    ]
    for image in images:
        assert image.size == (240, 280)
    return len(images)


def check_scenes() -> list:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from .display import sdl2
    sdl2.SDL()          # the library itself must load (raises SDLError): install.sh fetches it
    from .config import Settings
    from .display.desktop import DesktopDisplay, DisplayUnavailable
    from .engine import Engine
    from .scenes import catalog
    from .scenes.base import QUALITY, SceneContext
    try:
        display = DesktopDisplay(fullscreen=False, window_size=(320, 180), renderer="software",
                                 hidden=True).open()
    except DisplayUnavailable as exc:
        print(f"mdisplay selftest: scenes not rendered: {exc.problem}", file=sys.stderr)
        return []
    rendered = []
    try:
        canvas = display.canvas
        settings = Settings()
        settings.set("transition_seconds", 0)
        target = canvas.target(320, 180, "selftest")
        clock = [1000.0]
        for scene_id in catalog.SCENE_IDS:
            engine = Engine(canvas, settings,
                            lambda: SceneContext(320, 180, QUALITY["eco"], settings, seed=3,
                                                 accelerated=False),
                            now=lambda: clock[0], synchronous=True)
            engine.request(scene_id, "selftest")
            with canvas.into(target):
                engine.draw()
                for _ in range(5):
                    clock[0] += 0.2
                    engine.update(0.2)
                clock[0] += 5.0
                engine.draw()
                pixels = canvas.read_rgba()
            failed = scene_id in engine.failed
            engine.close()
            assert not failed, f"{scene_id} failed"
            assert pixels[..., :3].max() > 0, f"{scene_id} drew nothing"
            rendered.append(scene_id)
        assert canvas.live_textures == 1, f"textures left behind: {canvas.live_textures - 1}"
    finally:
        display.close()
    return rendered


def main() -> int:
    started = time.monotonic()
    for name in MODULES:
        importlib.import_module(name)
    check_settings()
    screens = check_lcd()
    scenes = check_scenes()
    print(f"mdisplay selftest: {len(MODULES)} modules, settings, {screens} LCD screens, "
          f"{len(scenes)} scenes rendered offscreen in {time.monotonic() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
