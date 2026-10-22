"""mDisplay's application: settings, the desktop window, the scene engine, input,
and — under mFruit OS — the Whisplay LCD remote.

Threads: the render loop runs on the main thread and owns all state.
Other threads (the LCD's daemon events, the SDK input controller, signals)
only ``post`` commands, which also wakes the loop. Nothing busy-waits: the
loop sleeps in SDL until the next frame is due, an event arrives or a
timer needs attention; paused or hidden, it renders nothing at all.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import resource
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import controls, paths
from .config import SETTINGS, Settings, SettingsStore
from .display import sdl2
from .scenes import catalog
from .scenes.base import Quality, SceneContext, resolve_quality

log = logging.getLogger("mdisplay")

SAVE_DELAY = 1.5           # settings are written this long after the last change
CURSOR_HIDE_AFTER = 2.5    # seconds without mouse movement (windowed)
INFO_INTERVAL = 0.5
REDUCED_FPS = 20
# Software renderer: one of these steady rates, the fastest the device keeps up with.
STEADY_RATES = (30, 24, 20, 15, 12, 10, 8, 6)
ADAPT_EVERY = 3.0
HALF_SIZE_FROM = 1280       # straight to HDMI: modes this wide are drawn at half size
EXIT_OK, EXIT_USAGE, EXIT_NO_DISPLAY, EXIT_DEPENDENCY, EXIT_FAILED = 0, 2, 3, 4, 1


@dataclass
class Options:
    scene: str = ""
    quality: str = ""
    fullscreen: Optional[bool] = None
    display: str = ""
    size: Optional[tuple] = None
    renderer: str = "auto"
    session: str = ""
    duration: float = 0.0
    show_info: bool = False
    seed: int = 0
    standalone: bool = False
    lcd: bool = False
    screenshot: str = ""
    stats: str = ""
    video_driver: str = ""
    output: str = "auto"          # auto | desktop | hdmi
    synchronous: bool = False
    env: dict = field(default_factory=lambda: dict(os.environ))


class Application:
    def __init__(self, options: Options):
        self.options = options
        self.env = options.env
        self.store = SettingsStore(paths.settings_path(self.env))
        self.settings, problems = self.store.load()
        for problem in problems:
            log.warning("settings: %s", problem)
        self.problems = problems
        self.overridden: dict = {}
        self._override("scene", options.scene)
        self._override("quality", options.quality)
        self._override("fullscreen", options.fullscreen)
        self._override("display", options.display)
        self.commands: "queue.SimpleQueue" = queue.SimpleQueue()
        self.stop = False
        self.exit_code = EXIT_OK
        self.display = None
        self.engine = None
        self.overlay = None
        self.remote = None
        self.quality: Optional[Quality] = None
        self.paused_by: set = set()
        self.hidden = False
        self.focused = True
        self.panel_open = False
        self.panel_index = 0
        self.confirm_reset_until = 0.0
        self.dirty_at: Optional[float] = None
        self.redraw = True
        self.last_mouse = 0.0
        self.started = time.monotonic()
        self.capture_next = False
        self.seed = options.seed or int(time.time()) & 0x7FFFFFFF
        self.stats = None
        self.clock = None
        self.pacer = None
        self.status = "starting"
        self.display_error = None
        self._depth = 0
        self.steady_fps = None
        self.adapt_at = 0.0

    # ------------------------------------------------------------ helpers
    def _override(self, key: str, value) -> None:
        if value in (None, ""):
            return
        original = self.settings[key]
        try:
            self.settings.set(key, value)
        except ValueError as exc:
            raise SystemExit(f"mdisplay: {exc}") from exc
        self.overridden[key] = original

    def post(self, command: str, *args) -> None:
        """Queue a command from any thread and wake the render loop."""
        self.commands.put((command, args))
        display = self.display
        if display is not None:
            display.wake()

    @property
    def standalone(self) -> bool:
        return self.remote is None

    @property
    def paused(self) -> bool:
        return bool(self.paused_by)

    # ---------------------------------------------------------------- run
    def run(self) -> int:
        self._block_signals()
        if self.options.duration > 0:
            self._watchdog(self.options.duration + 15.0)
        try:
            self._start_remote()
            if not self._open_display():
                if self.remote is None:
                    return self.exit_code
                self._wait_without_display()
                if self.stop:
                    return self.exit_code
            self._loop()
        finally:
            self._shutdown()
        return self.exit_code

    def _block_signals(self) -> None:
        wanted = {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}
        try:
            signal.pthread_sigmask(signal.SIG_BLOCK, wanted)
        except (AttributeError, OSError, ValueError):
            return

        def wait():
            while True:
                number = signal.sigwait(wanted)
                log.info("signal %d: closing", number)
                self.post(controls.EXIT, "signal")

        threading.Thread(target=wait, name="mdisplay-signals", daemon=True).start()

    @staticmethod
    def _watchdog(seconds: float) -> None:
        def expire():
            log.error("did not exit %d s after --duration; forcing exit", int(seconds))
            os._exit(124)
        timer = threading.Timer(seconds, expire)
        timer.daemon = True
        timer.start()

    def _start_remote(self) -> None:
        if self.options.standalone:
            return
        if not (self.options.lcd or paths.managed(self.env)):
            return
        from .remote import Remote
        self.remote = Remote(self)
        if not self.remote.start():
            log.warning("the Whisplay LCD is not available; running on the desktop only")
            self.remote = None

    # -------------------------------------------------------------- display
    def _open_display(self) -> bool:
        from .display.desktop import DesktopDisplay, DisplayUnavailable
        from .display import session as sessions
        self.status = "looking for the desktop"
        self._remote_update()
        output = self.options.output
        if output == "hdmi" and not self.options.video_driver:
            return self._open_kms(None)
        if not self.options.video_driver:
            result = sessions.find_session(self.env, self.options.session)
            if result.chosen is None:
                if output == "auto" and not self.options.session:
                    return self._open_kms(result)      # no desktop: draw on HDMI directly
                self._display_failed(result.problem, result.remedy,
                                     [f"{c.candidate.describe()}: {c.message}" for c in result.checks])
                return False
            sessions.apply(result.chosen)
            log.info("desktop session %s (%s)", result.chosen.describe(), result.chosen.source)
        else:
            os.environ["SDL_VIDEODRIVER"] = self.options.video_driver
        try:
            import numpy  # noqa: F401  (scenes need it; say so before opening a window)
        except ImportError:
            self._display_failed("NumPy is not installed.",
                                 "Install it: sudo apt install python3-numpy (or run install.sh).",
                                 [], code=EXIT_DEPENDENCY)
            return False
        icon = self._icon()
        display = DesktopDisplay(fullscreen=bool(self.settings["fullscreen"]),
                                 display_key=self.settings["display"],
                                 window_size=self.options.size, renderer=self.options.renderer,
                                 icon_rgba=icon)
        try:
            display.open()
        except DisplayUnavailable as exc:
            display.close()
            self._display_failed(exc.problem, exc.remedy, [f"{n}: {e}" for n, e in display.attempts],
                                 code=EXIT_DEPENDENCY if "SDL" in exc.problem else EXIT_NO_DISPLAY)
            return False
        self.display = display
        self.display_error = None
        self._start_engine()
        return True

    def _open_kms(self, session_result) -> bool:
        """No desktop session: drive the HDMI port directly (DRM/KMS), drawing in software."""
        from .display import kms
        details = [f"{c.candidate.describe()}: {c.message}" for c in session_result.checks] \
            if session_result is not None else []
        try:
            import numpy  # noqa: F401
        except ImportError:
            self._display_failed("NumPy is not installed.", "Run install.sh again (it fetches "
                                 "NumPy) or: sudo apt install python3-numpy", [], code=EXIT_DEPENDENCY)
            return False
        wanted = self.settings["display"]
        if not any(wanted.startswith(name) for name in kms.CONNECTOR_TYPES.values()):
            wanted = "auto"
        out = kms.KmsOutput(wanted=wanted, prefer_small=True)
        try:
            out.open()
        except kms.KmsError as exc:
            out.close()
            problem = exc.problem
            if session_result is not None and not session_result.headless:
                problem = f"{session_result.problem} {exc.problem}"
            self._display_failed(problem, exc.remedy, details + [str(c) for c in kms.survey()])
            return False
        return self._use_kms(out, details)

    def _use_kms(self, out, details: list) -> bool:
        """Draw with SDL's software renderer in a hidden window (dummy video driver) and
        hand each finished frame to ``out`` (an open kms.KmsOutput)."""
        from .display.desktop import DesktopDisplay, DisplayInfo, DisplayUnavailable
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        w, h = out.size
        # Software drawing costs per pixel: wide modes are drawn at half size and scaled
        # up once into the frame buffer (on an Orange Pi Zero 2W about 3x cheaper a frame).
        draw = (w // 2, h // 2) if w >= HALF_SIZE_FROM else (w, h)
        display = DesktopDisplay(fullscreen=False, window_size=draw, renderer="software",
                                 hidden=True)
        try:
            display.open()
        except DisplayUnavailable as exc:
            out.close()
            display.close()
            self._display_failed(exc.problem, exc.remedy, details,
                                 code=EXIT_DEPENDENCY if "SDL" in exc.problem else EXIT_NO_DISPLAY)
            return False
        display.kms = out
        display.fullscreen = True
        display.video_driver = "kms"
        mode = out.mode
        display.display = DisplayInfo(0, out.connector.name, 0, 0, w, h, mode.refresh,
                                      out.connector.name)
        display.displays_cache = [
            DisplayInfo(i, c.name, 0, 0, c.modes[0].width if c.modes else 0,
                        c.modes[0].height if c.modes else 0, 0, c.name)
            for i, c in enumerate(x for x in out.connectors if x.connected and x.external)]
        log.info("no desktop: drawing directly on %s (DRM/KMS, software renderer)", out.describe())
        self.display = display
        self.display_error = None
        self._start_engine()
        return True

    def _display_failed(self, problem: str, remedy: str, details: list,
                        code: int = EXIT_NO_DISPLAY) -> None:
        log.error("%s %s", problem, remedy)
        for line in details:
            log.info("  %s", line)
        self.display_error = (problem, remedy, details)
        self.exit_code = code
        self.status = "no display"
        self._remote_update()

    def _icon(self):
        try:
            import numpy as np
            from PIL import Image
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "assets", "icon.png")
            with Image.open(path) as image:
                return np.asarray(image.convert("RGBA").resize((64, 64)), np.uint8).copy()
        except Exception:
            return None

    def _wait_without_display(self) -> None:
        """Under mFruit OS with no desktop: the LCD shows the problem and offers Retry,
        Details and Back; settings can still be changed there. No retry loop runs by itself."""
        while not self.stop and self.display is None:
            try:
                command, args = self.commands.get(timeout=self._idle_timeout(None))
            except queue.Empty:
                command = None
            if command == "retry":
                if self._open_display():
                    return
                continue
            if command is not None:
                self.handle(command, *args)
            if self.remote is not None and self.remote.next_refresh() <= 0:
                self.remote.refresh()
            self._save_if_due()

    def _start_engine(self) -> None:
        from .engine import Engine
        from .timing import AnimationClock, FramePacer, FrameStats
        from .ui.overlay import Overlay
        display = self.display
        self.quality = resolve_quality(self.settings["quality"], display.accelerated)
        self.clock = AnimationClock()
        self.clock.speed = float(self.settings["speed"])
        self.pacer = FramePacer(60)
        self.stats = FrameStats()
        self.overlay = Overlay()
        self.overlay.resized(*display.size)
        self.overlay.set_info(self.options.show_info)
        self.engine = Engine(display.canvas, self.settings, self._context, on_notice=self._notice,
                             on_scene=self._scene_started, synchronous=self.options.synchronous)
        self.engine.set_sleep(float(self.settings["sleep_minutes"]))
        self.engine.request(self.settings["scene"], "start")
        self._apply_rate()
        display.allow_screensaver(bool(self.settings["allow_screen_blanking"]))
        if display.notice:
            self._notice(display.notice, 9.0)
        for problem in self.problems:
            self._notice("Settings: " + problem, 6.0)
        self.status = "showing"
        self._remote_update()

    def _context(self) -> SceneContext:
        w, h = self.display.size
        return SceneContext(w, h, self.quality, self.settings, seed=self.seed,
                            accelerated=self.display.accelerated,
                            max_texture=self.display.canvas.max_texture,
                            gentle=self.gentle)

    @property
    def gentle(self) -> bool:
        from .scenes.base import resolve_motion
        return resolve_motion(self.settings["motion"],
                              bool(self.display and self.display.accelerated))

    # ----------------------------------------------------------------- loop
    def _loop(self) -> None:
        display = self.display
        while not self.stop:
            animating = self._needs_frames()
            timeout = self.pacer.remaining() if animating else self._idle_timeout(self.engine)
            for event in display.events(timeout if timeout > 0 else 0.0):
                self._sdl_event(event)
            self._drain()
            if self.stop:
                break
            if self.engine.timers() == "sleep":
                self._sleep_timer_ended()
            self._mouse_idle()
            self._save_if_due()
            if self.remote is not None and self.remote.next_refresh() <= 0:
                self.remote.refresh()
            if self.options.duration and time.monotonic() - self.started >= self.options.duration:
                if self.options.screenshot and not self.capture_next:
                    self.capture_next = True
                    self.redraw = True
                elif not self.options.screenshot:
                    self.stop = True
                    break
            if (self._needs_frames() and self.pacer.remaining() <= 0) or self.redraw:
                self._frame()
                self._adapt_rate()

    def _needs_frames(self) -> bool:
        if self.hidden:
            return False
        return (self.engine.animating and not self.paused) or self.engine.busy or \
            self.overlay.busy() or self.capture_next

    def _idle_timeout(self, engine) -> float:
        deadlines = [30.0]
        if engine is not None:
            next_timer = engine.next_timer()
            if next_timer is not None:
                deadlines.append(next_timer + 0.01)
        if self.dirty_at is not None:
            deadlines.append(max(0.0, self.dirty_at + SAVE_DELAY - time.monotonic()))
        if self.confirm_reset_until:
            deadlines.append(max(0.0, self.confirm_reset_until - time.monotonic()))
        if self.options.duration:
            deadlines.append(max(0.0, self.started + self.options.duration - time.monotonic()))
        if self.display is not None and self.display.cursor_visible and not self.display.fullscreen:
            deadlines.append(max(0.05, self.last_mouse + CURSOR_HIDE_AFTER - time.monotonic()))
        if self.remote is not None:
            deadlines.append(self.remote.next_refresh())
        return max(0.01, min(deadlines))

    def _frame(self) -> None:
        start = time.perf_counter()
        canvas = self.display.canvas
        canvas.draw_calls = 0
        self.clock.paused = self.paused or self.hidden
        real, dt = self.clock.tick()
        if self.engine.paused != self.paused:
            self.engine.pause(self.paused)
        self.engine.update(0.0 if self.clock.paused else dt)
        self.engine.draw(float(self.settings["brightness"]))
        self._update_info(real)
        self.overlay.draw(canvas, real if real > 0 else 1 / 60)
        if self.capture_next:
            self._capture(canvas)
        kms_out = getattr(self.display, "kms", None)
        if kms_out is not None:
            kms_out.show(self.display.scan_out)
        else:
            canvas.present()
        self.redraw = False
        work = time.perf_counter() - start
        if real > 0:
            self.stats.add(real, work)
        self.pacer.frame_done()

    def _capture(self, canvas) -> None:
        self.capture_next = False
        try:
            from PIL import Image
            pixels = canvas.read_rgba()
            Image.fromarray(pixels[..., :3]).save(self.options.screenshot)
            log.info("screenshot saved: %s", self.options.screenshot)
        except Exception as exc:
            log.error("screenshot failed: %s", exc)
        if self.options.duration:
            self.stop = True

    def _update_info(self, real: float) -> None:
        overlay = self.overlay
        if not overlay.info_enabled:
            return
        now = time.monotonic()
        if now < overlay.info_next:
            return
        overlay.info_next = now + INFO_INTERVAL
        summary = self.stats.summary()
        display = self.display
        w, h = display.size
        where = display.display.describe() if display.display else ""
        overlay.update_info([
            f"{summary['fps']:.0f} fps · frame {summary['frame_ms_p50']:.1f} ms "
            f"(95% {summary['frame_ms_p95']:.1f}) · work {summary['work_ms_p50']:.1f} ms",
            f"{display.driver} ({'GPU' if display.accelerated else 'software'}) · "
            f"{display.video_driver} · {w}×{h}{' · vsync' if display.vsync else ''}",
            f"{catalog.name(self.engine.scene_id or '')} · {self.quality.name} · "
            f"{self.display.canvas.draw_calls} draws · {where}",
        ])

    # --------------------------------------------------------------- events
    def _sdl_event(self, event) -> None:
        display = self.display
        if display.is_wake(event):
            return
        kind = event.type
        if kind in (sdl2.QUIT, sdl2.APP_TERMINATING):
            self.stop = True
        elif kind == sdl2.KEYDOWN:
            self._key(event)
        elif kind == sdl2.WINDOWEVENT and event.window == display.window_id:
            self._window_event(event)
        elif kind == sdl2.MOUSEMOTION:
            self.last_mouse = time.monotonic()
            if not display.fullscreen:
                display.show_cursor(True)
        elif kind == sdl2.DISPLAYEVENT:
            self._display_event(event)
        elif kind == sdl2.RENDER_TARGETS_RESET:
            log.warning("render targets reset")
            if self.engine.layer is not None:
                self.engine.layer.destroy()
                self.engine.layer = None
            self.redraw = True
        elif kind == sdl2.RENDER_DEVICE_RESET:
            log.warning("render device reset: rebuilding the scene")
            self.overlay.lost_textures()
            self.engine.device_reset()
            self.redraw = True

    def _window_event(self, event) -> None:
        sub = event.sub
        if sub in (sdl2.WINDOW_SIZE_CHANGED, sdl2.WINDOW_RESIZED):
            w, h = self.display.canvas.refresh_size()
            log.info("output resized to %dx%d", w, h)
            self.engine.resize(w, h)
            self.overlay.resized(w, h)
            self._refresh_panel()
            self.redraw = True
        elif sub in (sdl2.WINDOW_EXPOSED, sdl2.WINDOW_RESTORED, sdl2.WINDOW_SHOWN_EVENT,
                     sdl2.WINDOW_MAXIMIZED):
            if self.hidden and sub != sdl2.WINDOW_EXPOSED:
                self.hidden = False
                self.clock.resync()
                self.pacer.restart()
            self.redraw = True
        elif sub in (sdl2.WINDOW_MINIMIZED_EVENT, sdl2.WINDOW_HIDDEN_EVENT):
            self.hidden = True
        elif sub == sdl2.WINDOW_FOCUS_LOST:
            self._focus(False)
        elif sub == sdl2.WINDOW_FOCUS_GAINED:
            self._focus(True)
        elif sub == sdl2.WINDOW_CLOSE:
            self.stop = True
        elif sub in (sdl2.WINDOW_DISPLAY_CHANGED, sdl2.WINDOW_MOVED):
            self._display_moved()

    def _focus(self, focused: bool) -> None:
        self.focused = focused
        if not self.standalone:
            return                 # under mFruit OS the keys come from the LCD's input, not focus
        mode = self.settings["unfocused"]
        if not focused and mode == "pause":
            self.paused_by.add("unfocused")
        else:
            self.paused_by.discard("unfocused")
        self._apply_rate()
        self.redraw = True

    def _display_event(self, event) -> None:
        display = self.display
        display.displays_cache = display.list_displays()
        if event.sub == sdl2.DISPLAY_CONNECTED:
            log.info("a screen was connected")
            wanted = self.settings["display"]
            if wanted != "auto" and display.display and display.display.key != wanted:
                if not display.move_to(wanted):
                    self._notice(f"Back on {display.display.label}")
        elif event.sub == sdl2.DISPLAY_DISCONNECTED:
            log.info("a screen was disconnected")
            self._notice("A screen was disconnected")
        self._display_moved()
        self._refresh_panel()

    def _display_moved(self) -> None:
        display = self.display
        index = display.current_display_index()
        for info in display.displays_cache:
            if info.index == index:
                if display.display is None or display.display.key != info.key:
                    display.display = info
                    self._apply_rate()
                break

    def _key(self, event) -> None:
        name = key_name(event.sym, event.mod)
        if not name:
            return
        if event.repeat and name not in ("up", "down", "left", "right", "tab", "shift+tab"):
            return
        if self.panel_open:
            command = controls.lookup(controls.PANEL_KEYS, name)
        else:
            command = controls.lookup(controls.AMBIENT_KEYS, name)
        if command:
            self.handle(command)

    def _mouse_idle(self) -> None:
        display = self.display
        if display.cursor_visible and (display.fullscreen or
                                       time.monotonic() - self.last_mouse > CURSOR_HIDE_AFTER):
            display.show_cursor(False)

    # ------------------------------------------------------------- commands
    def _drain(self) -> None:
        while True:
            try:
                command, args = self.commands.get_nowait()
            except queue.Empty:
                return
            self.handle(command, *args)

    def handle(self, command: str, *args) -> None:
        self._depth += 1
        try:
            self._handle(command, *args)
        finally:
            self._depth -= 1
        if self._depth == 0 and not command.startswith("remote_"):
            self._remote_update()

    def _handle(self, command: str, *args) -> None:
        engine = self.engine
        if command == "remote_action":
            if self.remote is not None:
                self.remote.handle_action(args[0])
        elif command == "remote_armed":
            if self.remote is not None:
                self.remote.set_armed(args[0])
        elif command == "remote_refresh":
            if self.remote is not None:
                self.remote.refresh()
        elif command == controls.EXIT:
            self.stop = True
            if self.remote is not None:
                # Leaving from the LCD after a problem it showed is the user's choice,
                # not a failure for mFruit OS to report.
                self.exit_code = EXIT_OK
        elif command == controls.NEXT_SCENE:
            self._choose_scene(+1)
        elif command == controls.PREV_SCENE:
            self._choose_scene(-1)
        elif command == "scene":
            self._set("scene", args[0])
        elif command == controls.PAUSE:
            self._toggle_pause()
        elif command == controls.FULLSCREEN:
            self._set("fullscreen", not self.settings["fullscreen"])
            self._notice(f"Full screen: {self.settings.text('fullscreen')}", 1.6)
        elif command == controls.INFO:
            if self.overlay is not None:
                self.overlay.set_info(not self.overlay.info_enabled)
                self.redraw = True
        elif command == controls.PANEL:
            self._open_panel(not self.panel_open)
        elif command == controls.PANEL_CLOSE:
            self._open_panel(False)
        elif command in (controls.PANEL_NEXT, controls.PANEL_PREV):
            rows = self._menu()
            step = 1 if command == controls.PANEL_NEXT else -1
            self.panel_index = (self.panel_index + step) % len(rows)
            self._refresh_panel()
        elif command in (controls.PANEL_INC, controls.PANEL_DEC, controls.PANEL_SELECT):
            rows = self._menu()
            item = rows[max(0, min(self.panel_index, len(rows) - 1))]
            direction = -1 if command == controls.PANEL_DEC else 1
            self.activate(item.key, direction, select=command == controls.PANEL_SELECT)
            self._refresh_panel()
        elif command == "activate":
            self.activate(args[0], args[1] if len(args) > 1 else 1, select=True)
        elif command == "step":
            key, direction = args
            self.activate(key, direction)
        elif command == "reset":
            self._changed(self.settings.reset())
            self._notice("Settings reset to defaults")
        elif command == "retry":
            pass                        # already showing
        else:
            log.debug("unknown command %s", command)
        if engine is not None:
            self.redraw = True

    def activate(self, key: str, direction: int = 1, select: bool = False) -> None:
        """A menu row was chosen (select) or nudged left/right."""
        if key == controls.PAUSE:
            if select:
                self._toggle_pause()
            return
        if key == controls.EXIT:
            if select:
                self.stop = True
            return
        if key == "reset":
            now = time.monotonic()
            if not select:
                return
            if now < self.confirm_reset_until:
                self.confirm_reset_until = 0.0
                self._changed(self.settings.reset())
                self._notice("Settings reset to defaults")
            else:
                self.confirm_reset_until = now + 4.0
            return
        if key in SETTINGS:
            displays = self.display.displays_cache if self.display else []
            if controls.step_setting(self.settings, key, direction, displays):
                self._changed({key})
                self._notice(f"{SETTINGS[key].label}: {self._value_text(key)}", 1.8)

    def _value_text(self, key: str) -> str:
        if key == "display":
            return controls.display_text(self.settings["display"],
                                         self.display.displays_cache if self.display else [])
        return self.settings.text(key)

    def _set(self, key: str, value) -> None:
        try:
            changed = self.settings.set(key, value)
        except ValueError as exc:
            log.warning("%s", exc)
            return
        if changed:
            self._changed({key})

    def _choose_scene(self, direction: int) -> None:
        self._set("scene", catalog.neighbour(self.engine.scene_id if self.engine else
                                             self.settings["scene"], direction))

    def _toggle_pause(self) -> None:
        if "user" in self.paused_by or "sleep" in self.paused_by:
            self.paused_by.discard("user")
            self.paused_by.discard("sleep")
            self._notice("Playing", 1.2)
        else:
            self.paused_by.add("user")
            self._notice("Paused", 1.6)
        if self.clock is not None:
            self.clock.resync()
        self._update_screensaver()

    def _update_screensaver(self) -> None:
        if self.display is not None:
            self.display.allow_screensaver(bool(self.settings["allow_screen_blanking"])
                                           or "user" in self.paused_by or "sleep" in self.paused_by)

    def _changed(self, keys: set) -> None:
        """Apply changed settings to the running display and schedule a save."""
        if not keys:
            return
        for key in keys:
            self.overridden.pop(key, None)
        self.dirty_at = time.monotonic()
        if self.engine is None:
            return
        if "scene" in keys:
            self.engine.request(self.settings["scene"], "setting")
        if "speed" in keys:
            self.clock.speed = float(self.settings["speed"])
        if "fullscreen" in keys:
            self.display.set_fullscreen(bool(self.settings["fullscreen"]))
        if "display" in keys:
            notice = self.display.move_to(self.settings["display"])
            if notice:
                self._notice(notice, 6.0)
        if keys & {"quality", "motion"}:
            self.quality = resolve_quality(self.settings["quality"], self.display.accelerated)
            if self.engine.scene_id:
                self.engine._rebuild(self.engine.scene_id)
        if keys & {"quality", "vsync", "unfocused"}:
            self._apply_rate()
        if "allow_screen_blanking" in keys:
            self._update_screensaver()
        if "unfocused" in keys:
            self._focus(self.focused)
        self.engine.settings_changed(keys)
        self.redraw = True

    def _sleep_timer_ended(self) -> None:
        action = self.settings["sleep_action"]
        log.info("sleep timer ended: %s", action)
        if action == "exit":
            self.stop = True
        elif action == "pause":
            self.paused_by.add("sleep")
            self._notice("Sleep timer: paused")
            self._update_screensaver()
        else:
            self.engine.request("minimal", "sleep timer")
            self._notice("Sleep timer: minimal scene")
        self._remote_update()

    def _notice(self, message: str, seconds: float = 2.6) -> None:
        log.info("notice: %s", message)
        if self.overlay is not None:
            self.overlay.show_toast(message, seconds)
            self.redraw = True
        if self.remote is not None:
            self.remote.notice(message)

    def _scene_started(self, scene_id: str) -> None:
        if self.settings["show_scene_name"]:
            self.overlay.show_caption(scene_id)
        self._apply_rate()
        if self.remote is not None:
            self.remote.scene_started(scene_id)

    def _apply_rate(self) -> None:
        """Frame-rate cap from quality, the scenes shown and focus; vertical sync to match."""
        if self.display is None or self.pacer is None:
            return
        refresh = self.display.display.refresh if self.display.display else 0
        cap = self.quality.fps or refresh or 60
        cap = min(cap, 144)
        if self.engine is not None:
            for slot in (self.engine.current, self.engine.incoming):
                if slot is not None and slot.scene.max_fps:
                    cap = min(cap, slot.scene.max_fps)
        if self.standalone and not self.focused and self.settings["unfocused"] == "reduce":
            cap = min(cap, REDUCED_FPS)
        self.rate_cap = cap
        if self.steady_fps:
            cap = min(cap, self.steady_fps)
        mode = self.settings["vsync"]
        vsync = mode == "on" or (mode == "auto" and refresh and refresh <= cap * 1.15)
        if bool(vsync) != self.display.vsync:
            self.display.set_vsync(bool(vsync))
        self.pacer.set_fps(cap)

    def _adapt_rate(self) -> None:
        """Software renderer: settle on a steady frame rate the device keeps up with.

        Frames that come at an even rhythm look smoother than a faster but uneven
        rate (measured on an Orange Pi Zero 2W, where scenes take 30-100 ms to draw).
        Every few seconds the recent drawing time picks the fastest of STEADY_RATES
        that leaves a margin; it only rises again with a clear margin, so it does
        not hunt. Frames while a scene is being prepared are not counted."""
        display = self.display
        if display is None or display.accelerated or self.engine is None:
            return
        now = time.monotonic()
        if now < self.adapt_at:
            return
        self.adapt_at = now + ADAPT_EVERY
        if self.engine.busy or len(self.stats.work) < 15:
            return
        recent = sorted(list(self.stats.work)[-45:])
        work = recent[int(len(recent) * 0.8)]
        cap = getattr(self, "rate_cap", 30)
        current = self.steady_fps or cap
        choice = STEADY_RATES[-1]
        for rate in STEADY_RATES:
            if rate > cap:
                continue
            margin = 1.25 if rate > current else 1.1       # rising needs more room
            if 1.0 / rate >= work * margin + 0.003:
                choice = rate
                break
        if choice != self.steady_fps:
            log.info("steady frame rate %d fps (drawing takes %.0f ms)", choice, work * 1000)
            self.steady_fps = choice
            self._apply_rate()

    # ---------------------------------------------------------------- panel
    def _menu(self) -> list:
        state = {"paused": self.paused, "quality": self.quality.name if self.quality else "",
                 "gentle": self.gentle if self.display else None,
                 "sleep_remaining": self.engine.sleep_remaining() if self.engine else None,
                 "confirm_reset": time.monotonic() < self.confirm_reset_until}
        displays = self.display.displays_cache if self.display else []
        return controls.menu(self.settings, state, self.standalone, displays)

    def menu_state(self) -> list:
        return self._menu()

    def _open_panel(self, open_: bool) -> None:
        self.panel_open = open_
        if self.overlay is not None:
            self.overlay.show_panel(open_)
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        if not self.panel_open or self.overlay is None:
            return
        rows = self._menu()
        self.panel_index = max(0, min(self.panel_index, len(rows) - 1))
        w, h = self.display.size
        self.overlay.set_panel(rows, self.panel_index, controls.key_hints(controls.PANEL_KEYS),
                               "Settings", w, h)
        self.redraw = True

    # ----------------------------------------------------------------- LCD
    def snapshot(self) -> dict:
        """What the LCD remote shows (read on the render thread)."""
        engine = self.engine
        display = self.display
        return {
            "status": self.status,
            "scene": engine.scene_id if engine else self.settings["scene"],
            "showing": engine.showing_id if engine else None,
            "loading": bool(engine and engine.pending is not None),
            "paused": self.paused,
            "sleep_remaining": engine.sleep_remaining() if engine else None,
            "rotation_remaining": engine.rotation_remaining() if engine else None,
            "output": display.display.describe() if display and display.display else "",
            "renderer": (f"{display.driver} ({'GPU' if display.accelerated else 'software'})"
                         if display and display.canvas else ""),
            "size": display.size if display and display.canvas else (0, 0),
            "fps": self.stats.summary()["fps"] if self.stats else 0.0,
            "error": self.display_error,
            "quality": self.quality.name if self.quality else "",
        }

    def _remote_update(self) -> None:
        if self.remote is not None:
            self.remote.refresh()

    def thumbnail(self, width: int = 200):
        """A small copy of the frame on screen (the LCD shows it); None if unavailable."""
        if self.display is None or self.display.canvas is None or self.engine is None:
            return None
        try:
            canvas = self.display.canvas
            self.engine.draw(float(self.settings["brightness"]))
            pixels = canvas.read_rgba()
            from PIL import Image
            image = Image.fromarray(pixels[..., :3])
            height = max(1, int(width * image.height / max(1, image.width)))
            self.redraw = True
            return image.resize((width, height), Image.BILINEAR)
        except Exception as exc:
            log.debug("thumbnail failed: %s", exc)
            return None

    # ------------------------------------------------------------- shutdown
    def _save_if_due(self, force: bool = False) -> None:
        if self.dirty_at is None:
            return
        if not force and time.monotonic() - self.dirty_at < SAVE_DELAY:
            return
        data = self.settings.copy()
        for key, original in self.overridden.items():
            data.values[key] = original           # command-line choices are not saved
        if self.store.save(data):
            self.dirty_at = None
        else:
            self.dirty_at = time.monotonic() + 30.0   # try again later, not in a loop
            self._notice("Settings could not be saved")

    def _shutdown(self) -> None:
        self._save_if_due(force=True)
        summary = self.stats.summary() if self.stats else {}
        if self.options.stats:
            self._write_stats(summary)
        if self.engine is not None:
            self.engine.close()
        if self.overlay is not None:
            self.overlay.close()
        if self.display is not None:
            leaked = self.display.canvas.live_textures if self.display.canvas else 0
            if leaked:
                log.debug("%d textures still alive at exit (released with the renderer)", leaked)
            self.display.close()
            self.display = None
        if self.remote is not None:
            self.remote.stop()
        if summary.get("frames"):
            log.info("frames %d, %.1f fps, frame p95 %.1f ms", summary["frames"], summary["fps"],
                     summary["frame_ms_p95"])

    def _write_stats(self, summary: dict) -> None:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        elapsed = time.monotonic() - self.started
        display = self.display
        data = dict(summary)
        data.update({
            "elapsed_s": elapsed,
            "cpu_s": usage.ru_utime + usage.ru_stime,
            "cpu_percent_of_one_core": 100.0 * (usage.ru_utime + usage.ru_stime) / max(elapsed, 1e-6),
            "max_rss_mb": usage.ru_maxrss / 1024.0,
            "scene": self.engine.scene_id if self.engine else None,
            "quality": self.quality.name if self.quality else None,
            "gentle": self.gentle if display else None,
            "steady_fps": self.steady_fps,
            "renderer": display.driver if display else None,
            "accelerated": display.accelerated if display else None,
            "video_driver": display.video_driver if display else None,
            "size": list(display.size) if display and display.canvas else None,
            "vsync": display.vsync if display else None,
            "output": display.display.as_dict() if display and display.display else None,
        })
        try:
            with open(self.options.stats, "w") as handle:
                json.dump(data, handle, indent=2)
        except OSError as exc:
            log.error("cannot write stats: %s", exc)


_NAMED_KEYS = {
    sdl2.K_RIGHT: "right", sdl2.K_LEFT: "left", sdl2.K_UP: "up", sdl2.K_DOWN: "down",
    sdl2.K_RETURN: "enter", sdl2.K_KP_ENTER: "enter", sdl2.K_ESCAPE: "escape",
    sdl2.K_SPACE: "space", sdl2.K_TAB: "tab", sdl2.K_F11: "f11", sdl2.K_BACKSPACE: "backspace",
    sdl2.K_HOME: "home", sdl2.K_END: "end", sdl2.K_PAGEUP: "pageup", sdl2.K_PAGEDOWN: "pagedown",
}


def key_name(sym: int, mod: int) -> str:
    """The binding-table name for an SDL key; '' for keys with Ctrl/Alt/Super (left to the desktop)."""
    if mod & (sdl2.KMOD_CTRL | sdl2.KMOD_ALT | sdl2.KMOD_GUI):
        return ""
    name = _NAMED_KEYS.get(sym)
    if name == "tab" and mod & sdl2.KMOD_SHIFT:
        return "shift+tab"
    if name:
        return name
    if 32 < sym < 127:
        return chr(sym).lower()
    return ""
