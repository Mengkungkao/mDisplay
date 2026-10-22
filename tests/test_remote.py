"""The Whisplay LCD remote under mFruit OS: the SDK's InputController (button and
keys, unthreaded with a fake clock, as the app contract asks) drives the real
application. Every gesture in the footer tables does what it says; nothing
acts while the app does not own the LCD; every screen stays inside the chrome."""

import unittest

import numpy as np

import helpers
from app import controls
from app.scenes import catalog
from app.application import Application, Options
from app.remote import Remote
from app.ui import lcd
from mfruit_sdk.input import Action
from mfruit_sdk.keys import DOWN, UP, KeyEvent
from mfruit_sdk.ui.theme import CONTENT_BOTTOM, FOOTER_Y, SCREEN_W


class FakeBoard:
    app_id = "mdisplay"

    def __init__(self):
        self.has_focus = True
        self.frames = []
        self.on_press = self.on_release = self.on_exit_request = lambda *a: None
        self.on_focus_changed = lambda has_focus: None
        self.running = True

    def start(self):
        pass

    def stop(self):
        self.running = False

    def show(self, image):
        self.frames.append(image)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        env = {"MDISPLAY_DATA": self.tmp.path, "WHISPLAY_OS_APP_DATA": self.tmp.path,
               "HOME": self.tmp.path}
        self.app = Application(Options(video_driver="dummy", size=(320, 180), fullscreen=False,
                                       synchronous=True, seed=3, env=env))
        self.clock = helpers.FakeClock()
        self.board = FakeBoard()
        self.remote = Remote(self.app, board=self.board, keyboard=False, threaded=False,
                             clock=self.clock)
        self.app.remote = self.remote
        self.remote.input.start()
        self.remote.draw()
        self.assertTrue(self.app._open_display())

    def tearDown(self):
        self.remote.input.stop()
        self.app._shutdown()
        self.tmp.cleanup()

    # ------------------------------------------------------------ helpers
    def pump(self):
        self.app._drain()

    def step(self, seconds):
        self.clock.advance(seconds)
        self.remote.input.gestures.poll()
        self.pump()

    def clicks(self, count=1):
        for _ in range(count):
            self.remote.input.press()
            self.step(0.06)
            self.remote.input.release()
            self.step(0.1)
        self.step(0.6)

    def hold(self):
        self.remote.input.press()
        self.step(0.8)
        self.remote.input.release()
        self.step(0.6)

    def key(self, name, code, kind="key"):
        """As the SDK's decoder sends them: named keys down and up, characters down only."""
        self.remote.input.key_event(KeyEvent(kind, name, DOWN, code))
        if kind == "key":
            self.remote.input.key_event(KeyEvent(kind, name, UP, code))
        self.pump()

    def scene(self):
        return self.app.engine.scene_id

    # -------------------------------------------------------------- home
    def test_first_frame_is_the_remote_home(self):
        self.pump()
        self.assertEqual(self.remote.screen, "home")
        self.assertTrue(self.board.frames)
        self.assertEqual(self.board.frames[-1].size, (240, 280))

    def test_tap_next_scene_double_previous(self):
        self.assertEqual(self.scene(), "galaxy")
        self.clicks(1)
        self.assertEqual(self.scene(), "nightsky")
        self.assertEqual(self.app.settings["scene"], "nightsky")
        self.clicks(2)
        self.assertEqual(self.scene(), "galaxy")

    def test_triple_pauses_and_resumes(self):
        self.clicks(3)
        self.assertTrue(self.app.paused)
        self.clicks(3)
        self.assertFalse(self.app.paused)

    def test_hold_arms_then_opens_the_scene_list_on_release(self):
        self.remote.input.press()
        self.step(0.8)
        self.assertTrue(self.remote.armed)                   # "release to choose a scene"
        self.assertEqual(self.remote.screen, "home")         # nothing happens while held
        self.remote.input.release()
        self.step(0.1)
        self.assertEqual(self.remote.screen, "scenes")
        self.assertEqual(self.remote.index, 0)               # on the scene being shown

    def test_back_from_home_leaves_the_app(self):
        self.clicks(4)
        self.assertTrue(self.app.stop)

    def test_exit_request_from_mfruit_os(self):
        self.board.on_exit_request = None
        self.remote.start = lambda: True
        self.app.post(controls.EXIT, "daemon")
        self.pump()
        self.assertTrue(self.app.stop)

    # -------------------------------------------------------------- menu
    def open_settings(self):
        self.hold()                                           # Scenes
        self.taps(len(catalog.SCENE_IDS) - self.remote.index)  # to the Settings row
        self.hold()
        self.assertEqual(self.remote.screen, "menu")

    def taps(self, count):
        for _ in range(count):
            self.clicks(1)

    def test_menu_changes_a_setting_and_back_returns_to_the_scene_list(self):
        self.open_settings()
        items = self.app.menu_state()
        speed_row = [i.key for i in items].index("speed")
        for _ in range(speed_row):
            self.clicks(1)
        self.hold()
        self.assertEqual(self.app.settings["speed"], 1.25)
        self.clicks(3)                                        # 3x steps back
        self.assertEqual(self.app.settings["speed"], 1.0)
        self.clicks(4)
        self.assertEqual(self.remote.screen, "scenes")
        self.assertEqual(self.remote.index, len(catalog.SCENE_IDS))
        self.clicks(4)
        self.assertEqual(self.remote.screen, "home")
        self.assertFalse(self.app.stop)

    def test_menu_back_row(self):
        self.open_settings()
        items = self.app.menu_state()
        self.remote.index = len(items)                        # the Back row
        self.hold()
        self.assertEqual(self.remote.screen, "scenes")

    def test_reset_asks_first(self):
        self.app.settings.set("speed", 2.0)
        self.open_settings()
        self.remote.index = [i.key for i in self.app.menu_state()].index("reset")
        self.hold()
        self.assertEqual(self.remote.screen, "confirm")
        self.assertEqual(self.app.settings["speed"], 2.0)
        self.clicks(1)                                        # Cancel
        self.hold()
        self.assertEqual(self.app.settings["speed"], 2.0)
        self.remote.index = [i.key for i in self.app.menu_state()].index("reset")
        self.hold()
        self.hold()                                           # Reset
        self.assertEqual(self.app.settings["speed"], 1.0)

    # ------------------------------------------------------------ scenes
    def test_every_scene_can_be_chosen_on_the_device(self):
        self.hold()
        for index, scene_id in enumerate(catalog.SCENE_IDS):
            with self.subTest(scene=scene_id):
                self.assertEqual(self.remote.index, index)
                self.hold()                                   # show it
                self.assertEqual(self.app.settings["scene"], scene_id)
                self.assertEqual(self.app.engine.scene_id, scene_id)
                self.assertEqual(self.remote.screen, "scenes")    # stay to try another
                self.clicks(1)

    def test_the_scene_on_screen_is_marked(self):
        rows = lcd.scene_rows("aurora")
        marked = [row.label for row in rows if row.mark]
        self.assertEqual(marked, ["Aurora"])
        self.assertEqual([r.label for r in rows[-2:]], ["Settings", "Back"])
        self.assertEqual(len(rows), len(catalog.SCENE_IDS) + 2)

    def test_scene_list_back_and_pause(self):
        self.hold()
        self.clicks(3)
        self.assertTrue(self.app.paused)
        self.clicks(2)                                        # previous wraps to Back
        self.assertEqual(self.remote.index, len(catalog.SCENE_IDS) + 1)
        self.hold()
        self.assertEqual(self.remote.screen, "home")
        self.hold()
        self.clicks(4)
        self.assertEqual(self.remote.screen, "home")
        self.assertFalse(self.app.stop)

    # -------------------------------------------------------------- keys
    def test_keyboard_through_the_sdk(self):
        self.key("right", 106)
        self.assertEqual(self.scene(), "nightsky")
        self.key("left", 105)
        self.assertEqual(self.scene(), "galaxy")
        self.key("space", 57)
        self.assertTrue(self.app.paused)
        self.key("space", 57)
        self.assertFalse(self.app.paused)
        self.key("enter", 28)
        self.assertEqual(self.remote.screen, "scenes")
        self.key("escape", 1)
        self.assertEqual(self.remote.screen, "home")
        self.key("b", 48, kind="char")
        self.assertEqual(self.remote.screen, "menu")
        self.key("escape", 1)
        self.assertEqual(self.remote.screen, "home")
        self.key("q", 16, kind="char")
        self.assertTrue(self.app.stop)

    def test_typed_commands_redraw_the_lcd(self):
        frames = len(self.board.frames)
        self.key("f", 33, kind="char")                       # full screen on the HDMI screen
        self.assertGreater(len(self.board.frames), frames)
        self.assertEqual(self.remote.note, "Full screen: On")    # started windowed

    def test_nothing_acts_without_the_lcd(self):
        self.board.has_focus = False
        frames = len(self.board.frames)
        self.clicks(1)
        self.key("enter", 28)
        self.clicks(4)
        self.assertEqual(self.scene(), "galaxy")
        self.assertEqual(self.remote.screen, "home")
        self.assertFalse(self.app.stop)
        self.assertEqual(len(self.board.frames), frames, "drew without the screen")

    def test_a_key_pressed_elsewhere_is_ignored(self):
        self.board.has_focus = False
        self.remote.input.key_event(KeyEvent("key", "escape", DOWN, 1))
        self.board.has_focus = True
        self.remote.input.key_event(KeyEvent("key", "escape", UP, 1))
        self.pump()
        self.assertFalse(self.app.stop)

    def test_char_commands_cover_the_footer(self):
        # Every action the home footer advertises is implemented by a gesture.
        names = {action for _gesture, action in lcd.HOME_HINTS}
        self.assertEqual(names, {"next", "scenes", "pause", "previous", "exit"})
        self.remote.handle_action(Action("extra"))
        self.assertTrue(self.app.paused)


class LcdRenderingTests(unittest.TestCase):
    def assert_inside_chrome(self, image):
        pixels = np.asarray(image.convert("RGB")).astype(int)
        self.assertEqual(image.size, (240, 280))
        status = pixels[0:32]
        foot = pixels[FOOTER_Y - 2:FOOTER_Y + 16]
        self.assertGreater(len(np.unique(status.reshape(-1, 3), axis=0)), 5, "no status bar")
        self.assertGreater(len(np.unique(foot.reshape(-1, 3), axis=0)), 5, "no footer")
        # Nothing drawn in the corner insets of the content area's edges.
        self.assertLessEqual(SCREEN_W, pixels.shape[1])
        self.assertLess(CONTENT_BOTTOM, FOOTER_Y)

    def test_every_screen(self):
        from mfruit_sdk.status import Status
        from app.config import Settings
        status = Status(3, 64, False)
        items = controls.menu(Settings(), {"paused": False, "quality": "balanced",
                                           "sleep_remaining": 600}, standalone=False)
        for image in (lcd.home({"scene": "nebula", "output": "HDMI-1 · 1920×1080"}, status),
                      lcd.scenes("projector", 6, status), lcd.scenes("galaxy", 9, status, armed=True),
                      lcd.home({"scene": "solar", "loading": True}, status, armed=True),
                      lcd.menu(items, 0, status), lcd.menu(items, len(items), status),
                      lcd.problem("No desktop", "Log in on the HDMI screen.", ["Retry", "Details",
                                                                               "Back"], 1, status),
                      lcd.details("Details", ["a"] * 30, 8, status),
                      lcd.confirm("Reset settings?", "All of them.", 0, status)):
            self.assert_inside_chrome(image)

    def test_menu_rows_match_the_hdmi_panel(self):
        from app.config import Settings
        state = {"paused": True, "quality": "eco"}
        lcd_items = controls.menu(Settings(), state, standalone=False)
        panel_items = controls.menu(Settings(), state, standalone=True)
        self.assertEqual([i.key for i in lcd_items], [i.key for i in panel_items if i.key != "unfocused"])
        self.assertEqual(lcd_items[0].label, "Resume")


if __name__ == "__main__":
    unittest.main()
