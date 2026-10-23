"""The scene engine: which scene runs, transitions, rotation, pause and the sleep timer.

It knows nothing about the window, the keyboard or mFruit OS: it is given a
canvas and frame times, and asked to draw. Scenes are prepared on a worker
thread (NumPy texture generation can take a second at 1080p) while the
current scene keeps animating; the new one then cross-fades in.

A scene that raises while preparing, updating or drawing is closed and
reported (``on_notice``), and the engine falls back to the Minimal scene,
so one broken scene never stops the display.
"""

from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from .gfx.canvas import BLEND, MOD, Canvas
from .scenes import catalog
from .scenes.base import Scene, SceneContext

log = logging.getLogger("mdisplay.engine")

FALLBACK = "minimal"


class Slot:
    """One live scene and its own scene time."""

    def __init__(self, scene_id: str, scene: Scene):
        self.id = scene_id
        self.scene = scene
        self.t = 0.0

    def close(self) -> None:
        try:
            self.scene.close()
        except Exception:      # a scene's clean-up must not stop the display
            log.exception("closing %s failed", self.id)


class Engine:
    def __init__(self, canvas: Canvas, settings, make_context: Callable[[], SceneContext],
                 now: Callable[[], float] = time.monotonic,
                 on_notice: Callable[[str], None] = lambda text: None,
                 on_scene: Callable[[str], None] = lambda scene_id: None,
                 executor: Optional[ThreadPoolExecutor] = None, synchronous: bool = False):
        self.canvas = canvas
        self.settings = settings
        self.make_context = make_context
        self.now = now
        self.on_notice = on_notice
        self.on_scene = on_scene
        self.synchronous = synchronous
        self.executor = executor or (None if synchronous else
                                     ThreadPoolExecutor(1, thread_name_prefix="mdisplay-prepare"))
        self.current: Optional[Slot] = None
        self.incoming: Optional[Slot] = None
        self.fade_start = 0.0
        self.fade_seconds = 0.0
        self.pending_id: Optional[str] = None
        self.pending: Optional[Future] = None
        self.layer = None
        self.edges = None              # the soft-edge multiply layer, made per size and mode
        self.edges_key = None
        self.paused = False
        self.failed: set = set()
        self.last_change = now()
        self.sleep_deadline: Optional[float] = None
        self.slept = False
        self.closed = False
        self._wanted = None            # the newest preparation's token (see _context)

    # --------------------------------------------------------------- state
    @property
    def scene_id(self) -> Optional[str]:
        if self.incoming is not None:
            return self.incoming.id
        if self.pending_id is not None:
            return self.pending_id
        return self.current.id if self.current else None

    @property
    def showing_id(self) -> Optional[str]:
        """The scene fully on screen (the outgoing one during a cross-fade)."""
        return self.current.id if self.current else None

    @property
    def busy(self) -> bool:
        """Frames are needed even while paused (a scene is loading or fading in)."""
        return self.pending is not None or self.incoming is not None

    @property
    def animating(self) -> bool:
        return (not self.paused and self.current is not None) or self.busy

    def fade_progress(self) -> float:
        if self.incoming is None:
            return 1.0
        if self.fade_seconds <= 0:
            return 1.0
        return min(1.0, max(0.0, (self.now() - self.fade_start) / self.fade_seconds))

    # ---------------------------------------------------------- selection
    def request(self, scene_id: str, reason: str = "user") -> bool:
        """Start preparing ``scene_id``; False when it is already showing or coming."""
        if self.closed or scene_id not in catalog.SCENE_IDS:
            return False
        if scene_id == self.scene_id:
            return False
        log.info("scene %s requested (%s)", scene_id, reason)
        self.pending_id = scene_id
        context = self._context()
        cls = catalog.load(scene_id)
        if self.synchronous:
            future: Future = Future()
            try:
                scene = cls.create(context)
                scene.prepare()
                future.set_result(scene)
            except Exception as exc:     # reported like a worker failure
                future.set_exception(exc)
        else:
            future = self.executor.submit(self._prepare, cls, context)
        self.pending = future
        self.last_change = self.now()
        self.poll()
        return True

    def _context(self) -> SceneContext:
        context = self.make_context()
        if self.executor is not None:
            context.background = self.executor.submit
        # A preparation stops when the engine closes or a newer choice replaces it.
        token = object()
        self._wanted = token
        context.cancelled = lambda: self.closed or self._wanted is not token
        return context

    @staticmethod
    def _prepare(cls, context):
        scene = cls.create(context)
        scene.prepare()
        return scene

    def step(self, direction: int) -> str:
        target = catalog.neighbour(self.scene_id or self.settings["scene"], direction)
        self.request(target, "next" if direction > 0 else "previous")
        return target

    def poll(self) -> None:
        """Adopt a prepared scene (render thread)."""
        future = self.pending
        if future is None or not future.done():
            return
        scene_id = self.pending_id
        self.pending, self.pending_id = None, None
        try:
            scene = future.result()
            scene.resize(self.canvas.width, self.canvas.height)
            scene.setup(self.canvas)
        except Exception as exc:
            self._scene_failed(scene_id, exc, "preparing")
            return
        if self.incoming is not None:      # a newer choice replaces a fade in progress
            self._finish_fade()
        slot = Slot(scene_id, scene)
        self.incoming = slot
        self.fade_start = self.now()
        self.fade_seconds = float(self.settings["transition_seconds"]) if self.current else 1.2
        self.on_scene(scene_id)

    def _finish_fade(self) -> None:
        if self.incoming is None:
            return
        if self.current is not None:
            self.current.close()
        self.current, self.incoming = self.incoming, None

    def _scene_failed(self, scene_id: str, exc: BaseException, stage: str) -> None:
        log.error("scene %s failed while %s: %s\n%s", scene_id, stage, exc,
                  "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        self.failed.add(scene_id)
        self.on_notice(f"{catalog.name(scene_id)} could not be shown ({exc})")
        if scene_id != FALLBACK and FALLBACK not in self.failed and self.current is None:
            self.request(FALLBACK, "fallback")

    # ------------------------------------------------------------- timers
    def set_sleep(self, minutes: float) -> None:
        self.sleep_deadline = self.now() + minutes * 60.0 if minutes and minutes > 0 else None
        self.slept = False

    def sleep_remaining(self) -> Optional[float]:
        if self.sleep_deadline is None:
            return None
        return max(0.0, self.sleep_deadline - self.now())

    def rotation_remaining(self) -> Optional[float]:
        if not self.settings["auto_rotate"] or self.slept:
            return None
        return max(0.0, self.last_change + float(self.settings["rotate_minutes"]) * 60.0 - self.now())

    def timers(self) -> Optional[str]:
        """Check the rotation and sleep timers; returns "sleep" when the sleep timer ended."""
        remaining = self.sleep_remaining()
        if remaining is not None and remaining <= 0 and not self.slept:
            self.slept = True
            self.sleep_deadline = None
            return "sleep"
        rotation = self.rotation_remaining()
        if rotation is not None and rotation <= 0 and not self.paused and not self.busy:
            self.step(+1)
        return None

    def next_timer(self) -> Optional[float]:
        """Seconds until a timer needs attention (for an idle wait), or None."""
        values = [v for v in (self.sleep_remaining(), self.rotation_remaining()) if v is not None]
        return min(values) if values else None

    # ------------------------------------------------------------- frames
    def pause(self, paused: bool = True) -> None:
        self.paused = paused

    def update(self, dt: float) -> None:
        """Advance live scenes by ``dt`` scene-seconds (callers pass 0 while paused)."""
        for slot in (self.current, self.incoming):
            if slot is None:
                continue
            slot.t += dt
            try:
                slot.scene.update(dt, slot.t)
            except Exception as exc:
                self._drop(slot, exc, "updating")

    def _drop(self, slot: Slot, exc: BaseException, stage: str) -> None:
        slot.close()
        if slot is self.current:
            self.current = None
        if slot is self.incoming:
            self.incoming = None
        self._scene_failed(slot.id, exc, stage)

    def draw(self, brightness: float = 1.0) -> None:
        canvas = self.canvas
        self.poll()
        if self.incoming is not None and self.fade_progress() >= 1.0:
            self._finish_fade()
        if self.current is not None:
            self._draw_slot(self.current)
        else:
            canvas.clear((0, 0, 0))
        if self.incoming is not None:
            layer = self._layer()
            if layer is None:
                self._finish_fade()       # no render target: cut instead of fading
                if self.current is not None:
                    self._draw_slot(self.current)
            else:
                with canvas.into(layer):
                    self._draw_slot(self.incoming)
                p = self.fade_progress()
                p = p * p * (3.0 - 2.0 * p)
                canvas.image(layer, 0, 0, canvas.width, canvas.height, alpha=int(255 * p),
                             blend=BLEND)
        self._draw_edges()
        canvas.dim(1.0 - max(0.0, min(1.0, brightness)))

    def _draw_edges(self) -> None:
        """Fade every scene to black at the screen's border (the soft-edges setting)."""
        mode = self.settings.get("edge_fade", "off")
        canvas = self.canvas
        if mode == "off" or not canvas.width or not canvas.height:
            return
        key = (mode, canvas.width, canvas.height)
        if key != self.edges_key or self.edges is None or not self.edges.alive:
            from .gfx import sprites
            if self.edges is not None:
                self.edges.destroy()
            # The software renderer copies 1:1 far faster than it scales while blending.
            size = 384 if canvas.accelerated else max(canvas.width, canvas.height)
            self.edges = canvas.texture(sprites.screen_edges(canvas.width, canvas.height, mode, size),
                                        MOD, name="engine.edges")
            self.edges_key = key
        w, h = canvas.width, canvas.height
        if mode != "soft":
            canvas.image(self.edges, 0, 0, w, h)
            return
        # Only the border changes anything (the middle is white): four strips are far
        # cheaper than a full-screen multiply on the software renderer.
        from .gfx.sprites import EDGE_WIDTHS
        tex = self.edges
        sx, sy = tex.width / w, tex.height / h
        # Whole pixels: the software renderer truncates fractional rectangles.
        b = min(min(w, h) // 2 - 1, int(EDGE_WIDTHS["soft"] * min(w, h)) + 3)
        tx, ty = max(1, round(b * sx)), max(1, round(b * sy))
        canvas.image(tex, 0, 0, w, b, src=(0, 0, tex.width, ty))
        canvas.image(tex, 0, h - b, w, b, src=(0, tex.height - ty, tex.width, ty))
        canvas.image(tex, 0, b, b, h - 2 * b, src=(0, ty, tx, tex.height - 2 * ty))
        canvas.image(tex, w - b, b, b, h - 2 * b, src=(tex.width - tx, ty, tx, tex.height - 2 * ty))

    def _draw_slot(self, slot: Slot) -> None:
        try:
            slot.scene.draw(self.canvas)
        except Exception as exc:
            self._drop(slot, exc, "drawing")
            self.canvas.clear((0, 0, 0))

    def _layer(self):
        canvas = self.canvas
        if self.layer is not None and (self.layer.width, self.layer.height) != canvas.size:
            self.layer.destroy()
            self.layer = None
        if self.layer is None:
            try:
                self.layer = canvas.target(canvas.width, canvas.height, "engine.fade")
            except Exception as exc:
                log.warning("no render target for cross-fades: %s", exc)
                return None
        return self.layer

    # ------------------------------------------------------------ changes
    def resize(self, width: int, height: int) -> None:
        for slot in (self.current, self.incoming):
            if slot is not None and slot.scene.resize(width, height):
                self._rebuild(slot.id)

    def settings_changed(self, keys: set) -> None:
        if "sleep_minutes" in keys:
            self.set_sleep(float(self.settings["sleep_minutes"]))
        if keys & {"auto_rotate", "rotate_minutes"}:
            self.last_change = self.now()
            self.slept = False
        for slot in (self.current, self.incoming):
            if slot is None:
                continue
            try:
                rebuild = slot.scene.settings_changed(keys)
            except Exception as exc:
                self._drop(slot, exc, "applying settings")
                continue
            if rebuild:
                self._rebuild(slot.id)

    def _rebuild(self, scene_id: str) -> None:
        """Prepare the same scene again (new size or quality) and cross-fade to it."""
        if self.pending_id == scene_id:
            return
        current_id = self.scene_id
        if current_id == scene_id:
            # request() ignores the scene already showing; force a new copy.
            self.pending_id = None
            context = self._context()
            cls = catalog.load(scene_id)
            if self.synchronous:
                future: Future = Future()
                try:
                    future.set_result(self._prepare(cls, context))
                except Exception as exc:
                    future.set_exception(exc)
            else:
                future = self.executor.submit(self._prepare, cls, context)
            self.pending_id, self.pending = scene_id, future

    def device_reset(self) -> None:
        """Every texture was lost (SDL_RENDER_DEVICE_RESET): rebuild what is shown."""
        scene_id = self.scene_id
        for slot in (self.current, self.incoming):
            if slot is not None:
                slot.close()
        self.current = self.incoming = None
        self.layer = None
        self.edges = None
        if scene_id:
            self.pending_id = None
            self.request(scene_id, "device reset")

    def close(self) -> None:
        self.closed = True
        for slot in (self.current, self.incoming):
            if slot is not None:
                slot.close()
        self.current = self.incoming = None
        if self.layer is not None:
            self.layer.destroy()
            self.layer = None
        if self.edges is not None:
            self.edges.destroy()
            self.edges = None
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
