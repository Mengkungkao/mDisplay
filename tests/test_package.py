"""The package is a valid native mFruit OS app (manifest, hooks, SDK copy, contract)."""

import filecmp
import json
import os
import re
import subprocess
import sys
import unittest

import helpers
from app import __version__

ROOT = helpers.ROOT
MFRUIT_OS = os.environ.get("MFRUIT_OS") or os.path.expanduser("~/MFruitOS")
HAVE_OS = os.path.isfile(os.path.join(MFRUIT_OS, "scripts", "check-app.py"))


class PackageTests(unittest.TestCase):
    def manifest(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            return json.load(handle)

    def test_manifest_follows_the_app_contract(self):
        m = self.manifest()
        self.assertEqual(m["id"], "mdisplay")
        self.assertEqual(m["name"], "mDisplay")
        self.assertRegex(m["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(m["version"], __version__)
        self.assertEqual(m["entrypoint"], "run.sh")
        self.assertEqual(m["test"], "test.sh")
        self.assertEqual(m["exit_gesture"], "none")
        self.assertIs(m["disable_esc_exit_key"], True)
        self.assertIs(m["background"], False)
        self.assertEqual(m["min_os_version"], "1.4.0")
        self.assertLessEqual(len(m["description"]), 160)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, m["icon"])))

    def test_hooks_are_executable_shell_with_lf_endings(self):
        for name in ("run.sh", "install.sh", "test.sh"):
            path = os.path.join(ROOT, name)
            with open(path, "rb") as handle:
                data = handle.read()
            self.assertTrue(data.startswith(b"#!/bin/sh\n"), name)
            self.assertNotIn(b"\r\n", data, name)
            self.assertTrue(os.access(path, os.X_OK), name)
            self.assertEqual(subprocess.run(["sh", "-n", path]).returncode, 0, name)
        with open(os.path.join(ROOT, "run.sh")) as handle:
            self.assertIn('exec "$PYTHON" -m app.main', handle.read())

    def test_no_hook_asks_for_sudo(self):
        for name in ("run.sh", "install.sh", "test.sh"):
            with open(os.path.join(ROOT, name)) as handle:
                code = [line for line in handle if not line.lstrip().startswith("#")
                        and "echo" not in line]
            self.assertFalse(any(re.search(r"\bsudo\b", line) for line in code), name)

    def test_smoke_test_passes(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(["sh", os.path.join(ROOT, "test.sh")], capture_output=True,
                                text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from app.scenes import catalog
        self.assertIn(f"{len(catalog.SCENE_IDS)} scenes rendered offscreen", result.stdout)

    @unittest.skipUnless(HAVE_OS, "no mFruit OS checkout")
    def test_vendored_sdk_matches_mfruit_os(self):
        source = os.path.join(MFRUIT_OS, "mfruitos", "sdk")
        for folder, _dirs, files in os.walk(source):
            if "__pycache__" in folder:
                continue
            for name in files:
                if name.endswith(".py"):
                    rel = os.path.relpath(os.path.join(folder, name), source)
                    self.assertTrue(filecmp.cmp(os.path.join(folder, name),
                                                os.path.join(ROOT, "mfruit_sdk", rel), shallow=False),
                                    f"{rel} differs: run MFruitOS/scripts/sdk-sync.sh {ROOT}")

    @unittest.skipUnless(HAVE_OS, "no mFruit OS checkout")
    def test_contract_copy_matches_mfruit_os(self):
        self.assertTrue(filecmp.cmp(os.path.join(MFRUIT_OS, "docs", "apps", "APP_CONTRACT.md"),
                                    os.path.join(ROOT, ".claude", "rules", "mfruit-os-app.md"),
                                    shallow=False))

    @unittest.skipUnless(HAVE_OS, "no mFruit OS checkout")
    def test_mfruit_os_package_preflight(self):
        result = subprocess.run([sys.executable, os.path.join(MFRUIT_OS, "scripts", "check-app.py"),
                                 "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        tmp = helpers.TempDir()
        try:
            build = subprocess.run(["bash", os.path.join(ROOT, "tools", "build-release.sh"),
                                    "--out", tmp.path], capture_output=True, text=True, timeout=180,
                                   env=dict(os.environ, MFRUIT_OS=MFRUIT_OS))
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            self.assertIn("App package preflight passed", build.stdout)
            archives = [n for n in os.listdir(tmp.path) if n.endswith(".tar.gz")]
            self.assertEqual(archives, [f"mdisplay-{__version__}.tar.gz"])
            self.assertTrue(os.path.isfile(os.path.join(tmp.path, "SHA256SUMS")))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
