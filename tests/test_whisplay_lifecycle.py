"""The LCD side of the whisplay-daemon contract, against a scripted daemon:
Esc claimed before the screen is taken, a first frame at once, nothing drawn
after focus is revoked, a new framebuffer adopted when the daemon hands the
screen back, an exit request honoured, focus released on the way out.
(The full launch path with the real daemon is test_mfruitos_integration.py.)"""

import json
import os
import socket
import threading
import time
import unittest

import helpers
from app import controls, whisplay
from app.application import Application, Options
from app.remote import Remote

W, H = 240, 280


class ScriptedDaemon:
    """Enough of whisplay-daemon's socket protocol for one foreground app."""

    def __init__(self, directory):
        self.path = os.path.join(directory, "d.sock")
        self.directory = directory
        self.log = []
        self.subscribers = []
        self.token = 0
        self.fb = None
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(8)
        self.running = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.running:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def new_framebuffer(self):
        self.token += 1
        path = os.path.join(self.directory, f"fb{self.token}.bin")
        with open(path, "wb") as handle:
            handle.write(b"\0" * (W * H * 2))
        self.fb = path
        return path

    def _serve(self, conn):
        reader = conn.makefile("r")
        line = reader.readline()
        if not line:
            conn.close()
            return
        request = json.loads(line)
        cmd, payload = request["cmd"], request.get("payload") or {}
        self.log.append((cmd, payload))
        if cmd == "events.subscribe":
            conn.sendall(b'{"ok": true}\n')
            self.subscribers.append(conn)
            return
        reply = {"ok": True, "payload": {}}
        if cmd == "app.focus.acquire":
            self.new_framebuffer()
            reply["payload"] = {"session_token": f"t{self.token}"}
        elif cmd == "framebuffer.acquire":
            reply["payload"] = {"buffer_handle": self.fb, "stride": W * 2, "height": H}
        conn.sendall((json.dumps(reply) + "\n").encode())
        conn.close()

    def send(self, event, **payload):
        payload.setdefault("app_id", "mdisplay")
        data = (json.dumps({"event": event, "payload": payload}) + "\n").encode()
        for conn in list(self.subscribers):
            try:
                conn.sendall(data)
            except OSError:
                self.subscribers.remove(conn)

    def framebuffer_bytes(self, path=None):
        with open(path or self.fb, "rb") as handle:
            return handle.read()

    def stop(self):
        self.running = False
        for conn in self.subscribers:
            conn.close()
        self.server.close()


class LcdLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.daemon = ScriptedDaemon(self.tmp.path)
        self.saved_socket = whisplay.SOCKET_PATH
        whisplay.SOCKET_PATH = self.daemon.path
        env = {"MDISPLAY_DATA": self.tmp.path, "WHISPLAY_OS_APP_DATA": self.tmp.path,
               "HOME": self.tmp.path}
        self.app = Application(Options(video_driver="dummy", standalone=False, env=env))
        self.remote = Remote(self.app, keyboard=False)
        self.app.remote = self.remote

    def tearDown(self):
        self.remote.stop()
        self.daemon.stop()
        whisplay.SOCKET_PATH = self.saved_socket
        self.tmp.cleanup()

    def wait(self, condition, what, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.02)
        self.fail(f"timed out: {what}; daemon log {self.daemon.log}")

    def commands(self):
        return [cmd for cmd, _ in self.daemon.log]

    def posted(self, wait=0.3):
        """Commands the remote posted to the application (status refreshes included)."""
        time.sleep(wait)
        found = []
        while not self.app.commands.empty():
            found.append(self.app.commands.get()[0])
        return found

    def test_start_claims_esc_then_the_screen_then_draws(self):
        self.assertTrue(self.remote.start())
        cmds = self.commands()
        register = cmds.index("app.register")
        acquire = cmds.index("app.focus.acquire")
        self.assertLess(register, acquire, "Esc must be claimed before taking the screen")
        self.assertEqual(self.daemon.log[register][1], {"app_id": "mdisplay",
                                                        "disable_esc_exit_key": True})
        self.assertNotIn("launch_command", self.daemon.log[register][1])
        self.assertIn("framebuffer.acquire", cmds)
        self.assertTrue(any(self.daemon.framebuffer_bytes()), "no first frame on the LCD")

    def test_revoked_focus_stops_drawing_and_regained_focus_redraws(self):
        self.remote.start()
        self.wait(lambda: self.daemon.subscribers, "event subscription")
        first_fb = self.daemon.fb
        self.daemon.send("app_focus_revoked")
        self.wait(lambda: not self.remote.board.has_focus, "focus revoked")
        frames = self.remote.frames
        self.remote.draw()
        self.assertEqual(self.remote.frames, frames, "drew without the screen")
        # The daemon hands the screen back with a new session and framebuffer.
        new_fb = self.daemon.new_framebuffer()
        self.daemon.send("app_foreground_acquired", session_token=f"t{self.daemon.token}")
        self.wait(lambda: self.remote.board.has_focus, "focus regained")
        self.app._drain()
        self.wait(lambda: any(self.daemon.framebuffer_bytes(new_fb)), "redraw on the new framebuffer")
        self.assertNotEqual(first_fb, new_fb)

    def test_exit_request_reaches_the_application(self):
        self.remote.start()
        self.wait(lambda: self.daemon.subscribers, "event subscription")
        self.daemon.send("app_exit_requested")
        self.assertIn(controls.EXIT, self.posted(1.0))

    def test_events_for_other_apps_are_ignored(self):
        self.remote.start()
        self.wait(lambda: self.daemon.subscribers, "event subscription")
        self.daemon.send("app_exit_requested", app_id="someone-else")
        self.assertNotIn(controls.EXIT, self.posted(0.5))

    def test_stop_releases_focus(self):
        self.remote.start()
        self.remote.stop()
        self.assertEqual(self.commands()[-1], "app.focus.release")

    def test_no_daemon_means_no_remote(self):
        whisplay.SOCKET_PATH = os.path.join(self.tmp.path, "missing.sock")
        remote = Remote(self.app, keyboard=False)
        started = time.monotonic()
        self.assertFalse(remote.start())
        self.assertLess(time.monotonic() - started, 8.0)


if __name__ == "__main__":
    unittest.main()


class NoDesktopTests(unittest.TestCase):
    """Under mFruit OS without a desktop: the LCD explains, Back leaves with code 0."""

    def test_problem_screen_then_back(self):
        tmp = helpers.TempDir()
        daemon = ScriptedDaemon(tmp.path)
        saved = whisplay.SOCKET_PATH
        whisplay.SOCKET_PATH = daemon.path
        try:
            env = {"MDISPLAY_DATA": tmp.path, "WHISPLAY_OS_APP_DATA": tmp.path, "HOME": tmp.path}
            app = Application(Options(session=":96", standalone=False, env=env))
            remote = Remote(app, keyboard=False)
            app.remote = remote
            self.assertTrue(remote.start())
            self.assertFalse(app._open_display())
            app._remote_update()
            self.assertEqual(remote.screen, "problem")
            self.assertEqual(app.exit_code, 3)
            image = remote.last_frame
            self.assertEqual(image.size, (240, 280))
            from mfruit_sdk.input import Action
            remote.handle_action(Action("next"))
            remote.handle_action(Action("select"))           # Details
            self.assertEqual(remote.screen, "details")
            remote.handle_action(Action("back"))
            self.assertEqual(remote.screen, "problem")
            remote.handle_action(Action("back"))              # leave
            app._drain()
            self.assertTrue(app.stop)
            self.assertEqual(app.exit_code, 0)
            remote.stop()
        finally:
            daemon.stop()
            whisplay.SOCKET_PATH = saved
            tmp.cleanup()
