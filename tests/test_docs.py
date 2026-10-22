"""The documentation keeps up with the code: every setting and scene is
described, and every relative Markdown link resolves."""

import os
import re
import unittest

import helpers
from app.config import SCHEMA
from app.scenes import catalog

ROOT = helpers.ROOT
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class DocsTests(unittest.TestCase):
    def test_every_setting_is_documented(self):
        text = read("docs", "CONFIGURATION.md")
        for setting in SCHEMA:
            self.assertIn(f"`{setting.key}`", text, setting.key)

    def test_every_scene_is_in_the_readme(self):
        text = read("README.md")
        for info in catalog.SCENES:
            self.assertIn(f"| {info.name} |", text, info.name)

    def test_relative_links_resolve(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "mfruit_sdk", "__pycache__", ".claude")]
            for name in files:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                for target in LINK.findall(text):
                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    target = target.split("#", 1)[0]
                    resolved = os.path.normpath(os.path.join(folder, target))
                    self.assertTrue(os.path.exists(resolved),
                                    f"{os.path.relpath(path, ROOT)}: broken link {target}")


if __name__ == "__main__":
    unittest.main()
