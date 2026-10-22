"""Settings: defaults, validation, recovery from bad files, atomic saves."""

import json
import os
import stat
import unittest
from unittest import mock

import helpers
from app import config, paths
from app.config import DEFAULTS, SCHEMA, Settings, SettingsStore, parse


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.path = os.path.join(self.tmp.path, "settings.json")
        self.store = SettingsStore(self.path, clock=lambda: 1700000000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text: str) -> None:
        with open(self.path, "w") as handle:
            handle.write(text)

    def test_every_default_is_valid(self):
        for setting in SCHEMA:
            ok, value = setting.validate(setting.default)
            self.assertTrue(ok, setting.key)
            self.assertEqual(value, setting.default)

    def test_missing_file_gives_defaults_without_problems(self):
        settings, problems = self.store.load()
        self.assertEqual(problems, [])
        self.assertEqual(settings.values, DEFAULTS)

    def test_malformed_json_is_kept_as_evidence_and_defaults_load(self):
        self.write("{ this is not json")
        settings, problems = self.store.load()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertEqual(len(problems), 1)
        kept = [name for name in os.listdir(self.tmp.path) if ".corrupt-" in name]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.tmp.path, kept[0])) as handle:
            self.assertEqual(handle.read(), "{ this is not json")
        self.assertFalse(os.path.exists(self.path))

    def test_partial_write_is_treated_as_corrupt(self):
        self.write('{"scene": "aurora", "speed": 1.')
        settings, problems = self.store.load()
        self.assertEqual(settings["scene"], "galaxy")
        self.assertTrue(problems)

    def test_not_an_object(self):
        self.write("[1, 2, 3]")
        settings, problems = self.store.load()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertTrue(problems)

    def test_invalid_values_fall_back_one_by_one(self):
        self.write(json.dumps({"scene": "aurora", "speed": "fast", "quality": "insane",
                               "fullscreen": "yes", "brightness": 5.0, "display": "HDMI-1",
                               "sleep_minutes": 7, "meteor_frequency": float("nan")}))
        settings, problems = self.store.load()
        self.assertEqual(settings["scene"], "aurora")          # valid ones are kept
        self.assertEqual(settings["display"], "HDMI-1")
        self.assertEqual(settings["speed"], 1.0)
        self.assertEqual(settings["quality"], "auto")
        self.assertEqual(settings["fullscreen"], True)
        self.assertEqual(settings["brightness"], 1.0)          # clamped, not reset
        self.assertEqual(settings["sleep_minutes"], 0)
        self.assertEqual(settings["meteor_frequency"], 1.0)
        self.assertEqual(len(problems), 6)

    def test_unknown_future_keys_are_kept_and_written_back(self):
        self.write(json.dumps({"schema": 9, "scene": "nebula", "future_thing": {"a": 1}}))
        settings, problems = self.store.load()
        self.assertEqual(settings["scene"], "nebula")
        self.assertTrue(any("newer" in p for p in problems))
        self.assertTrue(self.store.save(settings))
        with open(self.path) as handle:
            data = json.load(handle)
        self.assertEqual(data["future_thing"], {"a": 1})
        self.assertEqual(data["scene"], "nebula")

    def test_missing_optional_keys_use_defaults(self):
        self.write(json.dumps({"scene": "minimal"}))
        settings, problems = self.store.load()
        self.assertEqual(problems, [])
        self.assertEqual(settings["speed"], DEFAULTS["speed"])

    def test_save_is_atomic_and_leaves_no_temporary_files(self):
        settings = Settings()
        settings.set("scene", "solar")
        self.assertTrue(self.store.save(settings))
        self.assertEqual(os.listdir(self.tmp.path), ["settings.json"])
        self.assertEqual(self.store.load()[0]["scene"], "solar")

    def test_a_failed_write_keeps_the_previous_file(self):
        settings = Settings()
        settings.set("scene", "solar")
        self.store.save(settings)
        settings.set("scene", "aurora")
        with mock.patch("json.dump", side_effect=OSError(28, "No space left on device")):
            self.assertFalse(self.store.save(settings))
        self.assertIn("No space left", self.store.last_error)
        self.assertEqual(self.store.load()[0]["scene"], "solar")
        self.assertEqual(os.listdir(self.tmp.path), ["settings.json"])

    @unittest.skipIf(os.geteuid() == 0, "root ignores permissions")
    def test_permission_error_is_reported_not_raised(self):
        os.chmod(self.tmp.path, stat.S_IRUSR | stat.S_IXUSR)
        try:
            self.assertFalse(self.store.save(Settings()))
            self.assertIn("cannot save", self.store.last_error)
        finally:
            os.chmod(self.tmp.path, stat.S_IRWXU)

    @unittest.skipIf(os.geteuid() == 0, "root ignores permissions")
    def test_unreadable_file_gives_defaults(self):
        self.write(json.dumps({"scene": "aurora"}))
        os.chmod(self.path, 0)
        try:
            settings, problems = self.store.load()
            self.assertEqual(settings["scene"], "galaxy")
            self.assertTrue(problems)
        finally:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def test_huge_file_is_refused(self):
        self.write('{"pad": "' + "x" * (config.MAX_FILE_BYTES + 10) + '"}')
        settings, problems = self.store.load()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertTrue(problems)


class SettingsValueTests(unittest.TestCase):
    def test_set_validates(self):
        settings = Settings()
        self.assertTrue(settings.set("speed", 2.0))
        self.assertFalse(settings.set("speed", 2.0))
        with self.assertRaises(ValueError):
            settings.set("speed", 9.0)
        with self.assertRaises(ValueError):
            settings.set("scene", "warp-drive")
        with self.assertRaises(ValueError):
            settings.set("display", "../../etc")

    def test_step_cycles_options_and_wraps(self):
        settings = Settings()
        self.assertEqual(settings.step("speed", 1), 1.25)
        self.assertEqual(settings.step("speed", -1), 1.0)
        settings.set("speed", 3.0)
        self.assertEqual(settings.step("speed", 1), 0.25)
        self.assertEqual(settings.step("fullscreen"), False)
        self.assertEqual(settings.step("quality", 1), "eco")

    def test_step_from_a_hand_edited_value_goes_to_the_next_option(self):
        settings = Settings({"speed": 1.1})
        self.assertEqual(settings.step("speed", 1), 1.25)
        settings = Settings({"speed": 1.1})
        self.assertEqual(settings.step("speed", -1), 1.0)

    def test_reset_reports_changed_keys(self):
        settings = Settings()
        settings.set("speed", 2.0)
        settings.set("scene", "aurora")
        self.assertEqual(settings.reset(), {"speed", "scene"})
        self.assertEqual(settings.values, DEFAULTS)

    def test_texts(self):
        settings = Settings()
        self.assertEqual(settings.text("speed"), "1×")
        self.assertEqual(settings.text("brightness"), "85%")
        settings.set("sleep_minutes", 90)
        self.assertEqual(settings.text("sleep_minutes"), "1 h 30")
        settings.set("meteor_frequency", 0.0)
        self.assertEqual(settings.text("meteor_frequency"), "Off")
        self.assertEqual(settings.text("scene"), "Galaxy")


class PathTests(unittest.TestCase):
    def test_mfruit_os_data_directory(self):
        env = {"WHISPLAY_OS_APP_DATA": "/data/mdisplay", "HOME": "/home/u"}
        self.assertTrue(paths.managed(env))
        self.assertEqual(paths.settings_path(env), "/data/mdisplay/settings.json")

    def test_desktop_data_directory(self):
        env = {"HOME": "/home/u"}
        self.assertFalse(paths.managed(env))
        self.assertEqual(paths.settings_path(env), "/home/u/.config/mdisplay/settings.json")
        env["XDG_CONFIG_HOME"] = "/cfg"
        self.assertEqual(paths.settings_path(env), "/cfg/mdisplay/settings.json")

    def test_override(self):
        self.assertEqual(paths.data_dir({"MDISPLAY_DATA": "/x", "WHISPLAY_OS_APP_DATA": "/y"}), "/x")

    def test_parse_ignores_schema_key(self):
        settings, problems = parse({"schema": 1})
        self.assertEqual(problems, [])
        self.assertEqual(settings.values, DEFAULTS)


if __name__ == "__main__":
    unittest.main()
