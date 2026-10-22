"""Finding the desktop session when mFruit OS starts mDisplay without DISPLAY:
candidates come from the environment, loginctl and this user's processes,
and only one that actually accepts a connection is used."""

import os
import subprocess
import unittest

import helpers
from app.display import session


def fake_proc(root, uid, processes):
    """processes: {pid: (environ dict, sessionid)} -> a /proc-like tree."""
    for pid, (environ, sessionid) in processes.items():
        base = os.path.join(root, str(pid))
        os.makedirs(base)
        with open(os.path.join(base, "environ"), "wb") as handle:
            handle.write(b"\0".join(f"{k}={v}".encode() for k, v in environ.items()) + b"\0")
        with open(os.path.join(base, "sessionid"), "w") as handle:
            handle.write(sessionid)
        os.chown(base, uid, -1) if os.geteuid() == 0 else None


def fake_loginctl(sessions):
    """sessions: [(id, uid, type, active)]"""
    def run(args, **_kwargs):
        if args[1] == "list-sessions":
            out = "\n".join(f"{sid} {uid} user seat0 tty2 active no -" for sid, uid, _t, _a in sessions)
        else:
            sid = args[2]
            match = [s for s in sessions if s[0] == sid][0]
            out = (f"Type={match[2]}\nActive={'yes' if match[3] else 'no'}\nRemote=no\nDisplay=\n"
                   "State=active\n")
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
    return run


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.proc = os.path.join(self.tmp.path, "proc")
        os.makedirs(self.proc)
        self.uid = os.getuid()
        self.checked = []
        self.x11_dir = os.path.join(self.tmp.path, "x11")      # no X sockets here
        self.run_base = os.path.join(self.tmp.path, "run-user")
        os.makedirs(self.x11_dir)
        os.makedirs(self.run_base)

    def tearDown(self):
        self.tmp.cleanup()

    def verify_x(self, accept):
        def verify(display, xauth):
            self.checked.append(("x11", display, xauth))
            return (display, xauth) in accept, "ok" if (display, xauth) in accept else "refused"
        return verify

    def find(self, env, accept=(), sessions=(), wayland_ok=False, explicit=""):
        def verify_w(display, run_dir):
            self.checked.append(("wayland", display, run_dir))
            return wayland_ok, "ok" if wayland_ok else "no compositor"
        return session.find_session(env, explicit, uid=self.uid, home=self.tmp.path,
                                    run=fake_loginctl(list(sessions)), proc=self.proc,
                                    verify_x=self.verify_x(set(accept)), verify_w=verify_w,
                                    x11_dir=self.x11_dir, run_base=self.run_base)

    def cookie(self, name="gdm-cookie"):
        path = os.path.join(self.tmp.path, name)
        open(path, "w").close()
        return path

    def test_display_found_in_the_active_sessions_processes(self):
        # Like mFruit OS's daemon: no DISPLAY of its own. gnome-shell has it.
        cookie = self.cookie()
        fake_proc(self.proc, self.uid, {
            4100: ({"DISPLAY": ":1", "XAUTHORITY": cookie, "XDG_SESSION_TYPE": "x11"}, "2"),
            900: ({"DISPLAY": ":5"}, "7"),
        })
        result = self.find({"HOME": self.tmp.path}, accept={(":1", cookie)},
                           sessions=[("2", self.uid, "x11", True)])
        self.assertIsNotNone(result.chosen)
        self.assertEqual(result.chosen.display, ":1")
        self.assertEqual(result.chosen.env["XAUTHORITY"], cookie)
        self.assertEqual(result.chosen.source, "active login session")
        self.assertTrue(result.chosen.active)

    def test_environment_is_tried_first_but_must_connect(self):
        cookie = self.cookie()
        fake_proc(self.proc, self.uid, {
            4100: ({"DISPLAY": ":1", "XAUTHORITY": cookie}, "2"),
        })
        result = self.find({"DISPLAY": ":0", "HOME": self.tmp.path}, accept={(":1", cookie)},
                           sessions=[("2", self.uid, "x11", True)])
        self.assertEqual(self.checked[0][1], ":0")             # the environment came first
        self.assertEqual(result.chosen.display, ":1")          # ...but did not connect
        self.assertFalse(result.checks[0].ok)

    def test_wayland_only_desktop(self):
        run_dir = os.path.join(self.tmp.path, "run")
        os.makedirs(run_dir)
        fake_proc(self.proc, self.uid, {
            300: ({"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": run_dir}, "3"),
        })
        result = self.find({"HOME": self.tmp.path}, sessions=[("3", self.uid, "wayland", True)],
                           wayland_ok=True)
        self.assertEqual(result.chosen.kind, "wayland")
        self.assertEqual(result.chosen.env["WAYLAND_DISPLAY"], "wayland-0")

    def test_headless_machine(self):
        result = self.find({"HOME": self.tmp.path})
        self.assertIsNone(result.chosen)
        self.assertTrue(result.headless)
        self.assertIn("headless", result.problem)
        self.assertIn("Log in", result.remedy)

    def test_session_found_but_refused(self):
        fake_proc(self.proc, self.uid, {4100: ({"DISPLAY": ":1"}, "2")})
        result = self.find({"HOME": self.tmp.path}, sessions=[("2", self.uid, "x11", True)])
        self.assertIsNone(result.chosen)
        self.assertFalse(result.headless)
        self.assertIn("may not open", result.problem)
        self.assertIn("XAUTHORITY", result.remedy)

    def test_explicit_session_only(self):
        cookie = self.cookie()
        fake_proc(self.proc, self.uid, {4100: ({"DISPLAY": ":1", "XAUTHORITY": cookie}, "2")})
        result = self.find({"HOME": self.tmp.path}, accept={(":1", cookie)}, explicit=":3",
                           sessions=[("2", self.uid, "x11", True)])
        self.assertIsNone(result.chosen)                       # never falls back silently
        self.assertTrue(all(display == ":3" for _k, display, _x in self.checked))
        self.assertIn(":3", result.problem)

    def test_other_users_sessions_are_ignored(self):
        result = self.find({"HOME": self.tmp.path}, sessions=[("9", self.uid + 1, "x11", True)])
        self.assertEqual(result.login_sessions, [])

    def test_apply_exports_only_the_chosen_session(self):
        environ = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":9"}
        candidate = session.Candidate("x11", ":1", {"DISPLAY": ":1", "XAUTHORITY": "/c"}, "test")
        session.apply(candidate, environ)
        self.assertEqual(environ["DISPLAY"], ":1")
        self.assertEqual(environ["XAUTHORITY"], "/c")
        self.assertNotIn("WAYLAND_DISPLAY", environ)
        self.assertEqual(environ["SDL_VIDEODRIVER"], "x11")
        environ = {"SDL_VIDEODRIVER": "dummy"}
        session.apply(candidate, environ)
        self.assertEqual(environ["SDL_VIDEODRIVER"], "dummy")   # an explicit driver wins


if __name__ == "__main__":
    unittest.main()


class SocketScanTests(SessionTests):
    def test_x_socket_and_cookie_on_disk(self):
        open(os.path.join(self.x11_dir, "X0"), "w").close()
        home_cookie = os.path.join(self.tmp.path, ".Xauthority")
        open(home_cookie, "w").close()
        result = self.find({"HOME": self.tmp.path}, accept={(":0", home_cookie)})
        self.assertEqual(result.chosen.display, ":0")
        self.assertEqual(result.chosen.source, "X11 socket")
