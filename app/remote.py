"""The Whisplay LCD as mDisplay's remote control, when mFruit OS runs it.

mFruit OS launches mDisplay like any app (ApplicationManager -> whisplay-
daemon -> mfruit-run -> run.sh). mDisplay then follows the daemon contract on
the LCD: it claims Esc, takes focus and the framebuffer, draws its first
frame at once, reads the button and keyboards only through the SDK's
InputController (keys come from mFruit OS's key hub), stops drawing when
focus is revoked, and on ``app_exit_requested`` or Back from its first
screen it exits, which hands the LCD back to mFruit OS.

Threads: the daemon events, the button and the keyboard call in from their
own threads; every handler only posts to the application, whose render
thread changes state and draws the LCD.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from mfruit_sdk.daemon import own_escape_key
from mfruit_sdk.input import BACK, CHAR, EXTRA, NEXT, PREVIOUS, SELECT, InputController
from mfruit_sdk.status import StatusMonitor

from . import controls, paths
from .application import EXIT_DEPENDENCY
from .scenes import catalog
from .ui import lcd
from . import whisplay
from .whisplay import WhisplayApp

log = logging.getLogger("mdisplay.remote")

NOTE_SECONDS = 2.0
PROBLEM_CHOICES = ("Retry", "Details", "Back")

# Keys typed on a keyboard (they arrive as characters through the SDK).
CHAR_COMMANDS = {" ": controls.PAUSE, "b": controls.PANEL, "m": controls.PANEL,
                 "q": controls.EXIT, "f": controls.FULLSCREEN, "i": controls.INFO}


class Remote:
    def __init__(self, app, board: Optional[WhisplayApp] = None, keyboard: bool = True,
                 threaded: bool = True, clock=time.monotonic):
        self.app = app
        self.clock = clock
        self.board = board or WhisplayApp(paths.APP_ID)
        self.screen = "starting"
        self.index = 0
        self.menu_parent = "home"
        self.armed = False
        self.note = ""
        self.note_until = 0.0
        self.details_first = 0
        self.last_frame = None
        self.frames = 0
        self.status = StatusMonitor(on_change=lambda _s: self.app.post("remote_refresh"))
        self.input = InputController(self._input, active=lambda: self.board.has_focus,
                                     on_armed=self._armed, app_id=self.board.app_id,
                                     keyboard=keyboard, threaded=threaded, clock=clock)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> bool:
        board = self.board
        board.on_press = self.input.press
        board.on_release = self.input.release
        board.on_exit_request = lambda: self.app.post(controls.EXIT, "daemon")
        board.on_focus_changed = self._focus_changed
        try:
            # Before taking the screen: a registration makes the daemon redraw its desktop.
            own_escape_key(board.app_id, whisplay.SOCKET_PATH)
        except Exception as exc:      # an older daemon or none: the start below decides
            log.info("could not claim Esc: %s", exc)
        try:
            board.start()
        except (OSError, RuntimeError) as exc:
            log.warning("whisplay-daemon unavailable: %s", exc)
            board.running = False
            return False
        self.status.start()
        self.input.start()
        self.draw()
        log.info("remote control on the Whisplay LCD")
        return True

    def stop(self) -> None:
        self.input.stop()
        self.status.stop()
        self.board.stop()

    def _focus_changed(self, has_focus: bool) -> None:
        self.input.reset()               # keys pressed elsewhere are not ours
        if has_focus:
            self.app.post("remote_refresh")

    # ---------------------------------------------------------------- input
    def _armed(self, armed: bool) -> None:
        self.app.post("remote_armed", armed)

    def _input(self, action) -> None:
        self.app.post("remote_action", action)

    def handle_action(self, action) -> None:
        """An SDK action (render thread)."""
        name = action.name
        log.debug("action %s on %s", name, self.screen)
        if name == CHAR:
            command = CHAR_COMMANDS.get(action.char.lower())
            if command == controls.PANEL:
                if self.screen == "home":
                    self.menu_parent = "home"
                    self._open("menu")
                else:
                    self._open("home")
            elif command:
                self.app.handle(command)
                self.draw()
            return
        handler = getattr(self, f"_on_{self.screen}", None)
        if handler is not None:
            handler(name)
        self.draw()

    def _on_starting(self, name: str) -> None:
        if name == BACK:
            self.app.handle(controls.EXIT)

    def _on_home(self, name: str) -> None:
        if name == NEXT:
            self.app.handle(controls.NEXT_SCENE)
        elif name == PREVIOUS:
            self.app.handle(controls.PREV_SCENE)
        elif name == EXTRA:
            self.app.handle(controls.PAUSE)
        elif name == SELECT:
            self._open_scenes()
        elif name == BACK:
            self.app.handle(controls.EXIT)     # Back from the first screen leaves the app

    def _open_scenes(self) -> None:
        self._open("scenes")
        scene = self.app.snapshot().get("scene")
        if scene in catalog.SCENE_IDS:
            self.index = catalog.SCENE_IDS.index(scene)

    def _on_scenes(self, name: str) -> None:
        count = len(catalog.SCENE_IDS) + 2            # + Settings and Back
        if name == NEXT:
            self.index = (self.index + 1) % count
        elif name == PREVIOUS:
            self.index = (self.index - 1) % count
        elif name == EXTRA:
            self.app.handle(controls.PAUSE)
        elif name == BACK:
            self._open("home")
        elif name == SELECT:
            if self.index < len(catalog.SCENE_IDS):
                scene_id = catalog.SCENE_IDS[self.index]
                self.app.handle("scene", scene_id)
                self.notify(f"Showing {catalog.name(scene_id)}")
            elif self.index == len(catalog.SCENE_IDS):
                self.menu_parent = "scenes"
                self._open("menu")
            else:
                self._open("home")

    def _on_menu(self, name: str) -> None:
        items = self.app.menu_state()
        count = len(items) + 1               # + the Back row
        if name == NEXT:
            self.index = (self.index + 1) % count
        elif name == PREVIOUS:
            self.index = (self.index - 1) % count
        elif name == BACK:
            self._leave_menu()
        elif name in (SELECT, EXTRA):
            if self.index >= len(items):
                self._leave_menu()
                return
            item = items[self.index]
            if item.key == "reset":
                self._open("confirm")
            elif item.key == controls.EXIT:
                self.app.handle(controls.EXIT)
            elif item.key == controls.PAUSE:
                self.app.handle(controls.PAUSE)
            else:
                self.app.activate(item.key, -1 if name == EXTRA else 1, select=True)

    def _leave_menu(self) -> None:
        if self.menu_parent == "scenes":
            self._open("scenes")
            self.index = len(catalog.SCENE_IDS)       # back on the Settings row
        else:
            self._open("home")

    def _on_confirm(self, name: str) -> None:
        if name in (NEXT, PREVIOUS):
            self.index = 1 - self.index
        elif name == BACK:
            self._open("menu")
        elif name == SELECT:
            if self.index == 0:
                self.app.handle("reset")
            self._open("menu")

    def _on_problem(self, name: str) -> None:
        if name == NEXT:
            self.index = (self.index + 1) % len(PROBLEM_CHOICES)
        elif name == PREVIOUS:
            self.index = (self.index - 1) % len(PROBLEM_CHOICES)
        elif name == BACK:
            self.app.post(controls.EXIT, "back")
        elif name == SELECT:
            choice = PROBLEM_CHOICES[self.index]
            if choice == "Retry":
                self.notify("Trying again…")
                self.app.post("retry")
            elif choice == "Details":
                self._open("details")
            else:
                self.app.post(controls.EXIT, "back")

    def _on_details(self, name: str) -> None:
        if name == NEXT:
            self.details_first += 4
        elif name == PREVIOUS:
            self.details_first = max(0, self.details_first - 4)
        elif name in (BACK, SELECT):
            self._open("problem" if self.app.display is None else "home")

    def _open(self, screen: str) -> None:
        if screen != self.screen:
            self.screen = screen
            self.index = 0
            self.details_first = 0
        self.draw()

    # -------------------------------------------------------------- updates
    def notice(self, text: str) -> None:
        self.notify(text)

    def notify(self, text: str) -> None:
        self.note = text
        self.note_until = self.clock() + NOTE_SECONDS

    def scene_started(self, scene_id: str) -> None:
        self.draw()

    def next_refresh(self) -> float:
        """Seconds until the remote needs the render thread (an expiring note)."""
        now = self.clock()
        due = [60.0]
        if self.note:
            due.append(max(0.0, self.note_until - now))
        return min(due)

    def refresh(self) -> None:
        """Called by the application after anything changed (render thread)."""
        app = self.app
        now = self.clock()
        if app.display_error is not None and app.display is None:
            if self.screen not in ("problem", "details"):
                self._open("problem")
        elif self.screen in ("starting", "problem") and app.display is not None:
            self._open("home")
        if self.note and now >= self.note_until:
            self.note = ""
        self.draw()

    def set_armed(self, armed: bool) -> None:
        self.armed = armed
        self.draw()

    # -------------------------------------------------------------- drawing
    def render(self):
        """The current LCD frame (a Pillow image)."""
        app = self.app
        status = self.status.sample()
        note = self.note if self.note and self.clock() < self.note_until else ""
        if self.screen == "starting":
            return lcd.starting(status=status)
        if self.screen == "problem":
            _problem, remedy, _details = app.display_error or ("", "", [])
            # A short heading fits the LCD; the full problem is under Details.
            heading = "Software missing" if app.exit_code == EXIT_DEPENDENCY else "No HDMI desktop"
            return lcd.problem(heading, remedy, list(PROBLEM_CHOICES), self.index, status,
                               self.armed)
        if self.screen == "details":
            return lcd.details("Details", self._details_lines(), self.details_first, status)
        if self.screen == "menu":
            items = app.menu_state()
            self.index = min(self.index, len(items))
            return lcd.menu(items, self.index, status, self.armed, note)
        if self.screen == "scenes":
            snap = app.snapshot()
            return lcd.scenes(snap.get("scene") or "", self.index, status, self.armed, note)
        if self.screen == "confirm":
            return lcd.confirm("Reset settings?", "Every mDisplay setting goes back to its default.",
                               self.index, status, self.armed)
        return lcd.home(app.snapshot(), status, self.armed, note)

    def _details_lines(self) -> list:
        app = self.app
        lines = []
        if app.display_error:
            problem, remedy, details = app.display_error
            lines += [problem, remedy, ""] + list(details)
        snap = app.snapshot()
        if snap.get("renderer"):
            lines.append(f"Renderer: {snap['renderer']}")
        if snap.get("output"):
            lines.append(f"Screen: {snap['output']}")
        lines.append(f"Scene: {catalog.name(snap.get('scene') or '')}")
        lines.append("More: run.sh --diagnose")
        return lines

    def draw(self) -> None:
        if not self.board.has_focus:
            return                       # never draw without the screen
        image = self.render()
        self.board.show(image)
        self.last_frame = image
        self.frames += 1
