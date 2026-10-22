"""Animation time, frame pacing and frame statistics.

All motion is driven by elapsed time, never by frame counts, so a scene
looks the same at 20, 60 or 144 frames per second.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

MAX_STEP = 0.1      # a stall (scene load, a busy machine) never becomes a visible jump


class AnimationClock:
    """Scene time: real time x speed, frozen while paused, with each step capped."""

    def __init__(self, now: Callable[[], float] = time.monotonic, max_step: float = MAX_STEP):
        self.now = now
        self.max_step = max_step
        self.t = 0.0
        self.speed = 1.0
        self.paused = False
        self._last = now()

    def tick(self) -> tuple:
        """(real seconds since the last tick, scene seconds advanced)."""
        current = self.now()
        real = max(0.0, current - self._last)
        self._last = current
        step = min(real, self.max_step)
        if self.paused:
            return real, 0.0
        dt = step * self.speed
        self.t += dt
        return real, dt

    def resync(self) -> None:
        """Forget the time spent not rendering (paused, hidden), so nothing jumps."""
        self._last = self.now()


class FramePacer:
    """Deadlines for frames at a target rate, without busy-waiting or catch-up bursts."""

    def __init__(self, fps: float, now: Callable[[], float] = time.monotonic):
        self.now = now
        self.fps = 0.0
        self.interval = 0.0
        self.deadline = now()
        self.set_fps(fps)

    def set_fps(self, fps: float) -> None:
        fps = max(1.0, float(fps))
        if fps != self.fps:
            self.fps = fps
            self.interval = 1.0 / fps

    def remaining(self) -> float:
        """Seconds until the next frame is due (0 when due)."""
        return max(0.0, self.deadline - self.now())

    def frame_done(self) -> None:
        """Schedule the next deadline; if more than a frame behind, restart from now."""
        current = self.now()
        self.deadline += self.interval
        if self.deadline < current - self.interval:
            self.deadline = current + self.interval
        elif self.deadline < current:
            self.deadline = current

    def restart(self) -> None:
        self.deadline = self.now()


class FrameStats:
    """Rolling frame-time statistics (the last ``window`` frames)."""

    def __init__(self, window: int = 600):
        self.times = deque(maxlen=window)
        self.work = deque(maxlen=window)
        self.frames = 0

    def add(self, frame_seconds: float, work_seconds: float = 0.0) -> None:
        self.times.append(frame_seconds)
        self.work.append(work_seconds)
        self.frames += 1

    @staticmethod
    def _percentile(values: list, fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return ordered[index]

    def summary(self) -> dict:
        times = list(self.times)
        work = list(self.work)
        total = sum(times)
        return {
            "frames": self.frames,
            "fps": (len(times) / total) if total > 0 else 0.0,
            "frame_ms_p50": 1000 * self._percentile(times, 0.50),
            "frame_ms_p95": 1000 * self._percentile(times, 0.95),
            "frame_ms_p99": 1000 * self._percentile(times, 0.99),
            "frame_ms_max": 1000 * (max(times) if times else 0.0),
            "work_ms_p50": 1000 * self._percentile(work, 0.50),
            "work_ms_p95": 1000 * self._percentile(work, 0.95),
        }

    def reset(self) -> None:
        self.times.clear()
        self.work.clear()
