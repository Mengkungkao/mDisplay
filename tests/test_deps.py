"""Requirements fetched without root (app/deps.py), against stand-in apt and dpkg
commands: nothing is downloaded and the system is not touched."""

import json
import os
import stat
import subprocess
import textwrap
import unittest
from unittest import mock

import helpers
from app import deps

FAKE_TOOLS = {
    # libfoo needs libbar, which this "system" already has.
    "apt-cache": """
        printf 'libfoo\\n  Depends: libbar\\nlibbar\\n  Depends: <virtual-thing>\\n'
        printf '%s\\n' "$@" | grep -q libbaz && printf 'libbaz\\n'
        exit 0
    """,
    "dpkg-query": """
        for p in "$@"; do [ "$p" = libbar ] && echo "libbar install ok installed"; done
        exit 0
    """,
    "apt-get": """
        [ -n "$FAIL_DOWNLOAD" ] && { echo "E: Failed to fetch libfoo" >&2; exit 100; }
        shift
        for p in "$@"; do : > "${p}_1.0_arm64.deb"; done
    """,
    "dpkg-deb": """
        deb=$(basename "$2"); dest=$3; name=${deb%%_*}
        mkdir -p "$dest/usr/lib/aarch64-linux-gnu" "$dest/usr/lib/python3/dist-packages/$name"
        : > "$dest/usr/lib/aarch64-linux-gnu/$name.so.1"
        [ "$name" = libfoo ] && : > "$dest/usr/lib/aarch64-linux-gnu/libSDL2-2.0.so.0"
        : > "$dest/usr/lib/python3/dist-packages/$name/__init__.py"
    """,
}


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.TempDir()
        self.bin = os.path.join(self.tmp.path, "bin")
        os.makedirs(self.bin)
        for name, body in FAKE_TOOLS.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as handle:
                handle.write("#!/bin/sh\n" + textwrap.dedent(body))
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.data = os.path.join(self.tmp.path, "data")
        path = self.bin + os.pathsep + os.environ.get("PATH", "")
        patcher = mock.patch.dict(os.environ, {"PATH": path})
        patcher.start()
        self.addCleanup(patcher.stop)
        quiet = mock.patch.object(deps, "say")
        quiet.start()
        self.addCleanup(quiet.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_packages_are_unpacked_into_the_data_folder(self):
        self.assertEqual(deps.fetch(self.data, ["libfoo"]), ["libfoo"])     # libbar is installed
        root = deps.sysroot(self.data)
        lib = os.path.join(root, "usr/lib/aarch64-linux-gnu")
        self.assertTrue(os.path.exists(os.path.join(lib, "libSDL2-2.0.so.0")))
        with open(os.path.join(root, "paths.json")) as handle:
            info = json.load(handle)
        self.assertEqual(info["packages"], ["libfoo"])
        # Paths are where the files are now, not the folder they were built in.
        self.assertEqual(info["lib_dirs"], [lib])
        self.assertEqual(info["sdl2"], os.path.join(lib, "libSDL2-2.0.so.0"))
        env = deps.environment(self.data, base={"LD_LIBRARY_PATH": "/opt/x"})
        self.assertEqual(env["LD_LIBRARY_PATH"], lib + os.pathsep + "/opt/x")
        self.assertIn(os.path.join(root, "usr/lib/python3/dist-packages"), env["PYTHONPATH"])
        self.assertEqual(env["MDISPLAY_SDL2"], info["sdl2"])
        # env.sh, as run.sh sources it, gives the same paths.
        shell = subprocess.run(["sh", "-c", f'. "{deps.env_file(self.data)}"; '
                                'printf "%s\\n%s" "$LD_LIBRARY_PATH" "$MDISPLAY_SDL2"'],
                               capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
        self.assertEqual(shell.stdout.splitlines(), [lib, info["sdl2"]])
        self.assertEqual([n for n in os.listdir(self.data) if n.startswith(".sysroot-")], [])

    def test_a_later_fetch_keeps_what_was_fetched_before(self):
        deps.fetch(self.data, ["libfoo"])
        self.assertEqual(deps.fetch(self.data, ["libfoo", "libbaz"]), ["libfoo", "libbaz"])
        root = deps.sysroot(self.data)
        with open(os.path.join(root, "paths.json")) as handle:
            self.assertEqual(json.load(handle)["packages"], ["libbaz", "libfoo"])
        lib = os.path.join(root, "usr/lib/aarch64-linux-gnu")
        self.assertTrue(os.path.exists(os.path.join(lib, "libbaz.so.1")))
        self.assertTrue(os.path.exists(os.path.join(lib, "libfoo.so.1")))

    def test_a_failed_download_leaves_the_earlier_sysroot_as_it_was(self):
        deps.fetch(self.data, ["libfoo"])
        before = sorted(os.listdir(deps.sysroot(self.data)))
        with mock.patch.dict(os.environ, {"FAIL_DOWNLOAD": "1"}):
            with self.assertRaisesRegex(RuntimeError, "apt-get download failed"):
                deps.fetch(self.data, ["libbaz"])
        self.assertEqual(sorted(os.listdir(deps.sysroot(self.data))), before)
        self.assertEqual([n for n in os.listdir(self.data) if n.startswith(".sysroot-")], [])

    def test_nothing_to_fetch_when_everything_is_installed(self):
        with mock.patch.object(deps, "installed", lambda packages: set(packages)):
            self.assertEqual(deps.fetch(self.data, ["libfoo"]), [])
        self.assertFalse(os.path.exists(deps.sysroot(self.data)))


class EnsureTests(unittest.TestCase):
    def test_still_missing_says_how_to_install_once_with_root(self):
        tmp = helpers.TempDir()
        self.addCleanup(tmp.cleanup)
        absent = [("SDL2", "libsdl2-2.0-0", "not found")]
        with mock.patch.object(deps, "missing", return_value=absent), \
                mock.patch.object(deps, "fetch", side_effect=RuntimeError("no network")), \
                mock.patch.object(deps, "say") as said:
            self.assertEqual(deps.ensure(tmp.path), 1)
        lines = [call.args[0] for call in said.call_args_list]
        self.assertIn("could not fetch them without root: no network", lines)
        self.assertIn("install them once with: sudo apt-get install libsdl2-2.0-0", lines)

    def test_nothing_missing_does_nothing(self):
        with mock.patch.object(deps, "missing", return_value=[]), \
                mock.patch.object(deps, "fetch") as fetch:
            self.assertEqual(deps.ensure("/nonexistent"), 0)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
