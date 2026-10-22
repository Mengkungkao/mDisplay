"""Shared test helpers. Importing this forces SDL's dummy video driver: no test
opens a window on a real screen, and no test needs a desktop session."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)

from app.config import Settings  # noqa: E402
from app.display.desktop import DesktopDisplay  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.scenes.base import QUALITY, SceneContext  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class Offscreen:
    """A hidden 'window' on SDL's dummy driver with the software renderer and a
    render target to draw into and read back."""

    def __init__(self, width: int = 320, height: int = 180):
        self.display = DesktopDisplay(fullscreen=False, window_size=(width, height),
                                      renderer="software", hidden=True).open()
        self.canvas = self.display.canvas
        self.resize(width, height)

    def resize(self, width: int, height: int) -> None:
        self.canvas.width, self.canvas.height = width, height
        self.target = self.canvas.target(width, height, "test")

    def engine(self, settings=None, clock=None, quality: str = "eco", seed: int = 3,
               gentle: bool = False) -> Engine:
        settings = settings or Settings()
        clock = clock or FakeClock()
        canvas = self.canvas
        return Engine(canvas, settings,
                      lambda: SceneContext(canvas.width, canvas.height, QUALITY[quality], settings,
                                           seed=seed, accelerated=False, gentle=gentle),
                      now=clock, synchronous=True)

    def frame(self, engine: Engine, brightness: float = 1.0):
        with self.canvas.into(self.target):
            engine.draw(brightness)
            return self.canvas.read_rgba()

    def close(self) -> None:
        self.display.close()


class TempDir:
    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="mdisplay-test-")

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)
