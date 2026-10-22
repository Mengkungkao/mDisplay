"""The desktop application: keys and window events from SDL, the settings panel,
saved settings, focus, the sleep timer, clean exits and actionable failures.
SDL's dummy driver stands in for the desktop: nothing appears on a screen."""

import json
import os
import signal
import struct
import subprocess
import sys
import time
import unittest

import numpy as np

import helpers
from app import controls
from app.application import Application, Options, key_name
from app.display import sdl2


def push(display, kind, window=True, sub=0, sym=0, mod=0, data1=0, data2=0):
    buf = display.sdl.new_event_buffer()
    struct.pack_into("<II", buf, 0, kind, 0)
    if kind in (sdl2.KEYDOWN, sdl2.KEYUP):
        struct.pack_into("<IBB", buf, 8, display.window_id, 1, 0)
        struct.pack_into("<iiH", buf, 16, 0, sym, mod)
    elif kind == sdl2.WINDOWEVENT:
        struct.pack_into("<IB", buf, 8, display.window_id if window else 0, sub)
        struct.pack_into("<ii", buf, 16, data1, data2)
    display.sdl.SDL_PushEvent(buf)


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.env = {"MDISPLAY_DATA": self.tmp.path, "HOME": self.tmp.path}
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app._shutdown()
        self.tmp.cleanup()

    def make(self, **kwargs):
        options = dict(video_driver="dummy", size=(320, 180), fullscreen=False, synchronous=True,
                       seed=3, standalone=True, env=self.env)
        options.update(kwargs)
        app = Application(Options(**options))
        self.assertTrue(app._open_display())
        self.apps.append(app)
        return app

    def pump(self, app, frames=1):
        for _ in range(frames):
            for event in app.display.events():
                app._sdl_event(event)
            app._drain()
            if app.engine.timers() == "sleep":
                app._sleep_timer_ended()
            app._mouse_idle()
            app._frame()

    def key(self, app, sym, mod=0):
        push(app.display, sdl2.KEYDOWN, sym=sym, mod=mod)
        self.pump(app)

    def saved(self):
        with open(os.path.join(self.tmp.path, "settings.json")) as handle:
            return json.load(handle)


class KeyTests(AppTestCase):
    def test_key_names(self):
        self.assertEqual(key_name(sdl2.K_RIGHT, 0), "right")
        self.assertEqual(key_name(ord("b"), 0), "b")
        self.assertEqual(key_name(sdl2.K_TAB, sdl2.KMOD_SHIFT), "shift+tab")
        self.assertEqual(key_name(ord("q"), sdl2.KMOD_CTRL), "")       # left to the desktop
        self.assertEqual(key_name(sdl2.K_F11, 0), "f11")

    def test_every_bound_key_has_a_name_and_a_handler(self):
        handled = set()
        for table in (controls.AMBIENT_KEYS, controls.PANEL_KEYS):
            for keys, command, _ in table:
                handled.add(command)
        for command in handled:
            self.assertTrue(hasattr(controls, command.upper()) or command in
                            ("next_scene", "prev_scene"), command)

    def test_arrows_change_scene_space_pauses(self):
        app = self.make()
        self.pump(app)
        self.assertEqual(app.engine.scene_id, "galaxy")
        self.key(app, sdl2.K_RIGHT)
        self.assertEqual(app.engine.scene_id, "nightsky")
        self.key(app, sdl2.K_LEFT)
        self.assertEqual(app.engine.scene_id, "galaxy")
        self.key(app, sdl2.K_SPACE)
        self.assertTrue(app.paused)
        self.key(app, sdl2.K_SPACE)
        self.assertFalse(app.paused)

    def test_f11_toggles_full_screen_and_it_is_saved(self):
        app = self.make()
        self.key(app, sdl2.K_F11)
        self.assertTrue(app.settings["fullscreen"])
        self.assertTrue(app.display.fullscreen)
        self.key(app, ord("f"))
        self.assertFalse(app.display.fullscreen)
        app._save_if_due(force=True)
        self.assertFalse(self.saved()["fullscreen"])

    def test_escape_and_q_exit_ctrl_q_does_not(self):
        app = self.make()
        self.key(app, ord("q"), sdl2.KMOD_CTRL)
        self.assertFalse(app.stop)
        self.key(app, sdl2.K_ESCAPE)
        self.assertTrue(app.stop)

    def test_window_close_exits(self):
        app = self.make()
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_CLOSE)
        self.pump(app)
        self.assertTrue(app.stop)

    def test_info_line(self):
        app = self.make()
        self.key(app, ord("i"))
        self.assertTrue(app.overlay.info_enabled)
        self.pump(app, 3)
        self.assertIsNotNone(app.overlay.info.pixels)


class PanelTests(AppTestCase):
    def test_panel_opens_moves_changes_and_closes(self):
        app = self.make()
        self.key(app, ord("b"))
        self.assertTrue(app.panel_open)
        self.assertIsNotNone(app.overlay.panel.pixels)
        rows = [item.key for item in app.menu_state()]
        for _ in range(rows.index("speed")):
            self.key(app, sdl2.K_DOWN)
        self.key(app, sdl2.K_RIGHT)
        self.assertEqual(app.settings["speed"], 1.25)
        self.key(app, sdl2.K_LEFT)
        self.key(app, sdl2.K_LEFT)
        self.assertEqual(app.settings["speed"], 0.75)
        self.key(app, sdl2.K_TAB, sdl2.KMOD_SHIFT)
        self.assertEqual(rows[app.panel_index], "transition_seconds")
        self.key(app, sdl2.K_ESCAPE)
        self.assertFalse(app.panel_open)
        self.assertFalse(app.stop)                       # Esc closed the panel, not the app

    def test_every_menu_row_does_something(self):
        app = self.make()
        self.key(app, sdl2.K_TAB)
        for index, item in enumerate(app.menu_state()):
            if item.key in (controls.EXIT, "reset", controls.PAUSE):
                continue
            with self.subTest(row=item.key):
                before = dict(app.settings.values)
                app.panel_index = index
                self.key(app, sdl2.K_RIGHT)
                self.assertNotEqual(app.settings.values, before, f"{item.key} changed nothing")

    def test_reset_needs_two_presses(self):
        app = self.make()
        app.settings.set("speed", 2.0)
        self.key(app, sdl2.K_TAB)
        app.panel_index = [i.key for i in app.menu_state()].index("reset")
        self.key(app, sdl2.K_RETURN)
        self.assertEqual(app.settings["speed"], 2.0)
        self.assertEqual(app.menu_state()[app.panel_index].label, "Press again to reset")
        self.key(app, sdl2.K_RETURN)
        self.assertEqual(app.settings["speed"], 1.0)

    def test_pause_and_exit_rows(self):
        app = self.make()
        self.key(app, sdl2.K_TAB)
        app.panel_index = 0
        self.key(app, sdl2.K_RETURN)
        self.assertTrue(app.paused)
        app.panel_index = [i.key for i in app.menu_state()].index(controls.EXIT)
        self.key(app, sdl2.K_RETURN)
        self.assertTrue(app.stop)


class SettingsPersistenceTests(AppTestCase):
    def test_changes_are_saved_and_command_line_choices_are_not(self):
        app = self.make(scene="aurora", quality="eco")
        self.assertEqual(app.settings["scene"], "aurora")
        self.key(app, sdl2.K_TAB)
        app.panel_index = [i.key for i in app.menu_state()].index("brightness")
        self.key(app, sdl2.K_LEFT)
        app._save_if_due(force=True)
        saved = self.saved()
        self.assertEqual(saved["brightness"], 0.8)
        self.assertEqual(saved["scene"], "galaxy")      # --scene is not saved
        self.assertEqual(saved["quality"], "auto")      # --quality neither

    def test_relaunch_restores_the_scene(self):
        app = self.make()
        self.key(app, sdl2.K_RIGHT)
        app._shutdown()
        self.apps.remove(app)
        again = self.make()
        self.assertEqual(again.settings["scene"], "nightsky")

    def test_a_corrupt_settings_file_is_reported_and_replaced(self):
        with open(os.path.join(self.tmp.path, "settings.json"), "w") as handle:
            handle.write("{{{")
        app = self.make()
        self.assertTrue(app.problems)
        self.assertEqual(app.settings["scene"], "galaxy")


class BehaviourTests(AppTestCase):
    def test_focus_loss_slows_down_or_pauses(self):
        app = self.make()
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_FOCUS_LOST)
        self.pump(app)
        self.assertLessEqual(app.pacer.fps, 20)
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_FOCUS_GAINED)
        self.pump(app)
        self.assertGreater(app.pacer.fps, 20)
        app.settings.set("unfocused", "pause")
        app._changed({"unfocused"})
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_FOCUS_LOST)
        self.pump(app)
        self.assertTrue(app.paused)

    def test_minimised_window_renders_nothing(self):
        app = self.make()
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_MINIMIZED_EVENT)
        self.pump(app)
        self.assertTrue(app.hidden)
        self.assertFalse(app._needs_frames())
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_RESTORED)
        self.pump(app)
        self.assertFalse(app.hidden)

    def test_paused_and_idle_means_no_frames(self):
        app = self.make()
        app.handle(controls.PAUSE)
        self.pump(app)
        self.assertTrue(app._needs_frames(), "the first fade-in still runs while paused")
        app.engine.fade_start -= 60                      # let the fade-in finish
        self.pump(app)
        app.overlay.toast_start = app.overlay.caption_start = -1e9
        self.assertIsNone(app.engine.incoming)
        self.assertFalse(app._needs_frames())
        self.assertGreaterEqual(app._idle_timeout(app.engine), 1.0)

    def test_sleep_timer_actions(self):
        app = self.make()
        app.settings.set("sleep_minutes", 15)
        app._changed({"sleep_minutes"})
        app.engine.sleep_deadline = app.engine.now() - 1
        self.pump(app)
        self.assertEqual(app.engine.scene_id, "minimal")
        app.settings.set("sleep_action", "pause")
        app.engine.set_sleep(15)
        app.engine.sleep_deadline = app.engine.now() - 1
        self.pump(app)
        self.assertIn("sleep", app.paused_by)
        app.settings.set("sleep_action", "exit")
        app.engine.set_sleep(15)
        app.engine.sleep_deadline = app.engine.now() - 1
        self.pump(app)
        self.assertTrue(app.stop)

    def test_resize_event_rebuilds_the_layout(self):
        app = self.make()
        push(app.display, sdl2.WINDOWEVENT, sub=sdl2.WINDOW_SIZE_CHANGED, data1=320, data2=180)
        self.pump(app, 2)
        self.assertEqual(app.display.size, (320, 180))

    def test_quality_auto_never_picks_ultra(self):
        app = self.make()
        self.assertEqual(app.quality.name, "eco")          # software renderer here
        from app.scenes.base import resolve_quality
        self.assertEqual(resolve_quality("auto", True).name, "balanced")
        self.assertEqual(resolve_quality("ultra", False).name, "ultra")


class ProcessTests(unittest.TestCase):
    """Run the app as mFruit OS or a user would: a separate process."""

    def setUp(self):
        self.tmp = helpers.TempDir()
        self.env = dict(os.environ, MDISPLAY_DATA=self.tmp.path, MDISPLAY_VIDEO_DRIVER="dummy",
                        PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        self.tmp.cleanup()

    def run_app(self, *args, timeout=60):
        return subprocess.run([sys.executable, "-m", "app.main", *args], cwd=helpers.ROOT,
                              env=self.env, capture_output=True, text=True, timeout=timeout)

    def test_runs_for_a_while_saves_a_screenshot_and_exits_cleanly(self):
        shot = os.path.join(self.tmp.path, "frame.png")
        stats = os.path.join(self.tmp.path, "stats.json")
        result = self.run_app("--windowed", "--size", "320x180", "--scene", "nightsky",
                              "--duration", "2", "--screenshot", shot, "--stats", stats)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        from PIL import Image
        with Image.open(shot) as image:
            self.assertEqual(image.size, (320, 180))
            self.assertGreater(np.asarray(image).max(), 40)
        with open(stats) as handle:
            data = json.load(handle)
        self.assertGreater(data["frames"], 5)
        self.assertEqual(data["renderer"], "software")
        self.assertEqual(data["scene"], "nightsky")

    def test_sigterm_closes_cleanly(self):
        proc = subprocess.Popen([sys.executable, "-m", "app.main", "--windowed", "--size", "160x90"],
                                cwd=helpers.ROOT, env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(2.0)                               # running and drawing
            self.assertIsNone(proc.poll())
            started = time.monotonic()
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=10)
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertEqual(proc.returncode, 0, err[-2000:])
            self.assertIn("signal", err)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_no_desktop_gives_an_actionable_error(self):
        env = dict(self.env)
        env.pop("MDISPLAY_VIDEO_DRIVER")
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        self.env = env
        result = self.run_app("--session", ":97", "--standalone")
        self.assertEqual(result.returncode, 3)
        self.assertIn("The selected desktop session :97 cannot be opened", result.stderr)

    def test_unknown_renderer_is_reported(self):
        result = self.run_app("--renderer", "vulkan", "--standalone")
        self.assertEqual(result.returncode, 3, result.stderr[-1000:])
        self.assertIn("Renderer vulkan is not available", result.stderr)

    def test_help_and_version(self):
        self.assertEqual(self.run_app("--help").returncode, 0)
        result = self.run_app("--version")
        self.assertIn("mDisplay", result.stdout)


if __name__ == "__main__":
    unittest.main()
