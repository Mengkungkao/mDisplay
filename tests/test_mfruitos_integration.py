"""mDisplay as a real mFruit OS app: install, launch, use, exit, relaunch, uninstall.

Runs the REAL whisplay-daemon code (mFruit OS's bundled driver, with its
simulated board from tests/real_daemon) and the REAL mFruit OS launcher
in-process, exactly as mFruit OS's own lifecycle tests do. The package is
sideloaded through mFruit OS's installer (install.sh and test.sh hooks run),
launched through ApplicationManager (ticket, daemon app.launch, mfruit-run,
run.sh), driven with simulated button presses on the LCD, and must hand the
screen back to mFruit OS when it exits.

The HDMI side uses SDL's dummy video driver here (MDISPLAY_VIDEO_DRIVER), so
nothing appears on this machine's screen: this test proves the mFruit OS
contract, not HDMI output.

Needs an mFruit OS checkout: MFRUIT_OS, else ~/MFruitOS. Skipped without one.
Never run it alongside another real-daemon suite (they share fake-app clean-up).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MFRUIT_OS = os.environ.get("MFRUIT_OS") or os.path.expanduser("~/MFruitOS")
HAVE_OS = os.path.isfile(os.path.join(MFRUIT_OS, "mfruitos", "launcher", "runtime.py"))


def _harness():
    import importlib.util
    for path in (os.path.join(MFRUIT_OS, "tests"), MFRUIT_OS):
        if path not in sys.path:
            sys.path.insert(0, path)
    # mFruit OS's own test helpers (an empty input-device directory, so the
    # launcher never grabs this machine's keyboards), loaded under another
    # name: mDisplay's tests have a helpers module too.
    spec = importlib.util.spec_from_file_location(
        "mfruitos_test_helpers", os.path.join(MFRUIT_OS, "tests", "helpers.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    from real_daemon import RealDaemon, find_whisplay_src, new_home
    from mfruitos.launcher.runtime import Runtime
    from mfruitos.paths import Paths
    return helpers, RealDaemon, find_whisplay_src, new_home, Runtime, Paths


@unittest.skipUnless(HAVE_OS, f"no mFruit OS checkout at {MFRUIT_OS} (set MFRUIT_OS)")
class MfruitOsIntegrationTests(unittest.TestCase):
    def setUp(self):
        helpers, RealDaemon, find_whisplay_src, new_home, Runtime, Paths = _harness()
        src = find_whisplay_src()
        if src is None:
            self.skipTest("the mFruit OS checkout has no Whisplay daemon")
        logging.getLogger("mfruitos").setLevel(logging.CRITICAL)
        self.home = new_home()
        self.package = os.path.join(self.home, "mdisplay-package")
        shutil.copytree(ROOT, self.package, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".pytest_cache", "dist", "tests"))
        self.daemon = RealDaemon(self.home)
        # Inherited by the daemon, so by mfruit-run and mDisplay.
        self.env_saved = {k: os.environ.get(k) for k in
                          ("WHISPLAY_DAEMON_SOCKET", "MDISPLAY_VIDEO_DRIVER", "PYTHONDONTWRITEBYTECODE")}
        os.environ["WHISPLAY_DAEMON_SOCKET"] = self.daemon.socket_path
        os.environ["MDISPLAY_VIDEO_DRIVER"] = "dummy"
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        self.daemon.start(src)
        paths = Paths(os.path.join(self.home, "os"), os.path.join(self.home, ".whisplay-daemon"))
        self.paths = paths
        self.rt = Runtime(paths, MFRUIT_OS, socket_path=self.daemon.socket_path,
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.settings.set("button.click_gap_ms", 200)
        self.thread = threading.Thread(target=self.rt.run, daemon=True)
        self.thread.start()
        self.wait(lambda: self.rt.focus.has_focus and not self.rt._booting
                  and self.rt.router.top is self.rt.home_screen, "mFruit OS home", 30)

    def tearDown(self):
        try:
            self.rt.loop.post(self.rt.shutdown, 0)
            self.thread.join(5)
        finally:
            self.daemon.stop()
            subprocess.run(["pkill", "-f", f"{self.home}/"], check=False)
            for key, value in self.env_saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(self.home, ignore_errors=True)

    # ------------------------------------------------------------ helpers
    def wait(self, condition, what, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}; daemon={self.daemon.state()}\n"
                  f"app log:\n{self.app_log()[-3000:]}")

    def app_log(self) -> str:
        try:
            with open(os.path.join(self.paths.logs_dir, "mdisplay.log"), errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

    def foreground(self):
        return self.daemon.state()["foreground"]

    def lcd(self):
        return self.daemon.state()["lcd"]

    def clicks(self, count: int = 1):
        """One gesture of ``count`` quick clicks (4 = back)."""
        for _ in range(count):
            self.daemon.press()
            time.sleep(0.05)
            self.daemon.release()
            time.sleep(0.08)
        time.sleep(0.6)          # past the SDK's 400 ms click window

    def taps(self, count: int):
        """``count`` separate taps, each its own gesture."""
        for _ in range(count):
            self.clicks(1)

    def hold(self):
        self.daemon.press()
        time.sleep(0.9)          # past the 700 ms long press: arms, acts on release
        self.daemon.release()
        time.sleep(0.4)

    def run_record(self) -> dict:
        with open(os.path.join(self.paths.home, "state", "runs", "mdisplay.json")) as handle:
            return json.load(handle)

    def settings(self) -> dict:
        path = os.path.join(self.paths.home, "apps", "mdisplay", "data", "settings.json")
        with open(path) as handle:
            return json.load(handle)

    def install(self):
        self.rt.loop.post(self.rt.sideload, self.package)
        self.wait(lambda: self.rt.registry.get("mdisplay") is not None
                  and not self.rt.tasks.busy("jobs"), "the package installed", 120)
        entry = self.rt.registry.get("mdisplay")
        self.assertEqual(entry.name, "mDisplay")
        self.assertEqual(entry.kind, "os")

    def launch(self):
        frame_before = self.lcd()
        self.rt.loop.post(self.rt.launch_app, "mdisplay", "control")
        self.wait(lambda: self.foreground() == "mdisplay", "mDisplay on the LCD", 30)
        self.wait(lambda: self.lcd() != frame_before, "mDisplay's first LCD frame", 10)
        self.wait(lambda: "scene galaxy requested" in self.app_log()
                  or "scene " in self.app_log(), "the scene engine", 20)

    def wait_home(self):
        self.wait(lambda: self.foreground() == "mfruit-os" and self.rt.focus.has_focus,
                  "back on mFruit OS Home", 15)
        self.wait(lambda: self.run_record().get("state") == "exited", "the run record", 10)

    # -------------------------------------------------------------- tests
    def test_install_launch_use_exit_relaunch_uninstall(self):
        self.install()
        version_dir = os.path.realpath(os.path.join(self.paths.home, "apps", "mdisplay", "current"))
        self.assertTrue(os.path.isfile(os.path.join(version_dir, "run.sh")))
        self.assertFalse(any("__pycache__" in d for d, _, _ in os.walk(version_dir)),
                         "the smoke test left bytecode in the installed version")

        # Launch from mFruit OS: the LCD shows mDisplay's remote, the scenes run.
        self.launch()
        log = self.app_log()
        self.assertIn("remote control on the Whisplay LCD", log)
        self.assertIn("renderer software", log)

        # On the LCD: hold opens the Scenes list (on Galaxy); 3 taps reach Aurora, hold shows it.
        self.hold()
        self.taps(3)
        self.hold()
        self.wait(lambda: "scene aurora requested" in self.app_log(), "Aurora chosen on the device")
        # 5 taps reach Settings, hold opens it; 5 taps reach Speed, hold changes it.
        self.taps(5)
        self.hold()
        self.taps(5)
        self.hold()
        # 4x back to Scenes, 4x to the remote's home, 4x leaves the app.
        self.clicks(4)
        self.clicks(4)
        self.clicks(4)
        self.wait_home()
        record = self.run_record()
        self.assertEqual(record.get("exit_code"), 0, record)
        self.assertEqual(self.settings()["speed"], 1.25, self.app_log()[-4000:])
        self.assertEqual(self.settings()["scene"], "aurora")

        # Relaunch: the setting is still there; mFruit OS's exit request closes it.
        self.launch()
        started = time.monotonic()
        entry = self.rt.registry.get("mdisplay")
        self.assertTrue(self.rt.lifecycle.request_stop(entry))     # daemon app.exit.request
        self.wait_home()
        self.assertLess(time.monotonic() - started, 6.0)
        self.assertEqual(self.run_record().get("exit_code"), 0)
        self.assertEqual(self.settings()["speed"], 1.25)
        alive = subprocess.run(["pgrep", "-f", f"{self.paths.home}/apps/mdisplay"],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(alive, "", "an mDisplay process outlived its session")

        # Uninstall through mFruit OS (data is kept, as mFruit OS does).
        done = threading.Event()
        self.rt.loop.post(self.rt.uninstall_app, "mdisplay", lambda kept: done.set())
        self.wait(done.is_set, "the uninstall", 30)
        self.assertFalse(os.path.exists(os.path.join(self.paths.home, "apps", "mdisplay", "current")))

    def test_force_stop_releases_the_lcd_and_ends_cleanly(self):
        # mFruit OS stops an app's process group (SIGTERM) when it does not leave by itself.
        self.install()
        self.launch()
        entry = self.rt.registry.get("mdisplay")
        started = time.monotonic()
        self.assertTrue(self.rt.lifecycle.force_stop(entry))
        self.wait_home()
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(self.run_record().get("exit_code"), 0, self.app_log()[-2000:])
        self.assertIn("signal", self.app_log())


if __name__ == "__main__":
    unittest.main()
