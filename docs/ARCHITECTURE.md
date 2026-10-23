# mDisplay architecture

How mDisplay is built and why. Rules it follows are mFruit OS's
([app contract](../.claude/rules/mfruit-os-app.md), mFruit OS
`docs/platform/DEVELOPMENT_RULES.md`); status words (IMPLEMENTED, AUTOMATED,
DEVICE VERIFIED, NOT VERIFIED) are used as defined there.

## Where it sits

```text
mFruit OS launcher ── ApplicationManager ── whisplay-daemon app.launch ── mfruit-run ── run.sh
                                                                                         │
                                                                     python3 -m app.main │
 ┌───────────────────────────────────────────────────────────────────────────────────────┘
 │
 │  Whisplay LCD (240x280)                          HDMI screen (the desktop's)
 │  app/remote.py  ── daemon contract,              app/display/desktop.py ── one SDL window
 │  SDK InputController, SDK chrome                 found by app/display/session.py
 │        │  posts commands                                  │ events
 │        ▼                                                  ▼
 │  app/application.py: the render thread owns all state; settings; HDMI panel; sleep timer
 │        │
 │        ▼
 │  app/engine.py: scene lifecycle, worker-thread preparation, cross-fades, rotation, soft edges
 │        │
 │        ▼
 │  app/scenes/*.py  ──  draw only through  ──  app/gfx/canvas.py (textures, batches, meshes)
 │                                                       │
 │                                                       ▼
 └──────────────────────────────────────  app/display/sdl2.py (ctypes binding to libSDL2)
```

mDisplay is an mFruit OS **application** (layer A). It changes nothing in
mFruit OS: no platform module, manifest field, daemon behaviour or Whisplay
driver file. When a desktop session (X11 or Wayland) runs, the HDMI screen
belongs to it and mDisplay is an ordinary client of that desktop, the way an
app is a client of the sound server. Without one (the usual mFruit OS device),
mDisplay drives the HDMI port itself through DRM/KMS and gives it back to the
console on exit ([display backends](DISPLAY_BACKENDS.md)). The Whisplay framebuffer is only
ever used through the daemon, for the 240×280 LCD.

## Decisions

### 1. SDL2 through ctypes, not pygame

| Considered | Outcome |
|---|---|
| pygame (SDL2) | Rejected after a prototype: `Texture.draw` rounds positions to whole pixels, so very slow drifts step visibly; each sprite is a Python call; a 13 MB wheel per Python version |
| pyglet / moderngl + shaders | Need OpenGL 3.3 (not on every small board) and a second binding (PyOpenGL) whose EGL/GLX selection breaks on Wayland |
| Tkinter | Too slow for full-screen animation |
| **SDL2's own renderer through ctypes** | **Chosen.** One library (`libSDL2`, usually already on a desktop); the GPU renderer (OpenGL or OpenGL ES) when present, SDL's software renderer otherwise, chosen by SDL; float rectangles and `SDL_RenderGeometry` (SDL 2.0.18+) give sub-pixel motion and thousands of sprites per draw call; dummy video driver for headless tests |

Measured on the dev machine: 3000 sprites per frame cost ≈2.3 ms with
per-call drawing; with `SDL_RenderGeometry` the whole star field is one call.
`app/display/sdl2.py` declares every function's exact C signature in one
table (a wrong signature crashes rather than raises). Software rendering
rounds to whole pixels and has no custom blend modes; mDisplay detects both.

### 2. The LCD is a remote, the HDMI screen shows the scenes

Under mFruit OS an app must own the LCD while it runs (focus, first frame,
SDK input). Showing the scenes there would waste the HDMI screen; showing
nothing there would leave the user without controls. The LCD therefore shows
the name of the scene on the HDMI screen (not the scene itself: since 0.4.1 no
thumbnail is drawn, which also spares the board), the Scenes list and the
settings.
Run by hand on a desktop there is no LCD, and the same settings appear as a
panel on the HDMI screen. Both are built from one menu model
(`app/controls.py`), so they cannot drift apart.

### 3. Finding the desktop from a system service

whisplay-daemon starts apps from a systemd unit: no `DISPLAY`, `XAUTHORITY` or
`WAYLAND_DISPLAY`. `app/display/session.py` gathers candidates (an explicit
choice, its own environment, the environment of this user's processes in an
active `loginctl` session — e.g. gnome-shell on GDM keeps
`XAUTHORITY=/run/user/<uid>/gdm/Xauthority` — other user processes, then X11
and Wayland sockets on disk), and uses the first that **actually connects**
(`XOpenDisplay`, or connecting to the compositor's socket). Environment
variables are never taken as proof. Only the user's own processes are read;
nothing needs root.

### 4. Scenes are prepared off the render thread

Texture generation (NumPy noise, Pillow drawing) takes 0.1–5 s at 1080p. Each
scene splits into `prepare()` (CPU only, worker thread) and `setup(canvas)`
(upload, render thread); the current scene keeps animating while the next one
is prepared, then they cross-fade. Text is drawn on the render thread only
(FreeType faces are not shared between threads).

### 5. One owner per responsibility

| Responsibility | Owner |
|---|---|
| Launching, stopping, the Home entry, packages, updates, rollback | mFruit OS (unchanged) |
| LCD, button, focus | whisplay-daemon via `app/whisplay.py` (the template's client) |
| Button gestures and keyboard keys under mFruit OS | the SDK's `InputController` (mFruit OS key hub) |
| The window, displays, renderer, window keys | `app/display/desktop.py` |
| Which session/display to use | `app/display/session.py` |
| Scene lifecycle, fades, rotation, sleep timer, soft edges | `app/engine.py` |
| Settings schema, validation, persistence | `app/config.py` |
| Menus and key bindings (one table each) | `app/controls.py` |
| Drawing primitives | `app/gfx/canvas.py`, `app/gfx/batch.py` |

## Threads

| Thread | Job |
|---|---|
| main (render) | SDL events, all state, drawing, LCD frames; sleeps in `SDL_WaitEventTimeout` until a frame, an event or a timer is due; paused or hidden it draws nothing |
| `mdisplay-prepare` | `Scene.prepare()` (one at a time) |
| `mdisplay-signals` | `sigwait` for SIGTERM/SIGINT/SIGHUP → posts *exit* (blocked in every other thread, so mFruit OS's stop is handled cleanly) |
| whisplay events, SDK gestures, SDK keys, SDK status | only `post()` commands (which also wake SDL's wait) |

## Rendering

- Delta-time motion everywhere: `AnimationClock` gives scene seconds (real time
  × speed, steps capped at 0.1 s, frozen while paused). Tests check that 24,
  60 and 144 fps give the same picture.
- Frame pacing: `FramePacer` deadlines at the quality's cap (Eco 30, Balanced
  and High 60, Ultra the display's refresh up to 144), lower for calm scenes
  (Minimal 24) and for an unfocused window; vertical sync only when the
  display's refresh rate matches the cap, so a 144 Hz monitor is not driven at
  144 fps by default.
- Cross-fades render the incoming scene into a render target and blend it over
  the outgoing one. Soft edges are a small multiply texture over the scene;
  brightness is a black overlay; overlays (panel, toasts) are drawn last.
- Dark gradients are dithered, and on GPU renderers a moving grain tile hides
  8-bit banding.
- SDL's software renderer (a board without a GPU) is costly when it scales or
  turns images while blending, so scenes there pre-scale textures to the size
  they are drawn at (`Scene.fit`), bake fixed glows into the sky, and the
  galaxy is composed with Pillow at whole-degree steps (the next step on the
  engine's worker thread) and blended between steps. The application then
  settles on a steady frame rate from `STEADY_RATES` that the device keeps up
  with, measured every 3 s, and **gentle motion** (the `motion` setting, Auto =
  gentle without a GPU) keeps anything from travelling across the sky.
- Software-renderer specifics in 0.3.0: the inside galaxy's panorama is drawn as
  two whole-pixel copies blended (a smooth sub-pixel drift); the aurora's
  curtains are painted with NumPy into a small image each frame (polar
  coordinates around the zenith) because SDL rasterises long diagonal
  triangles slowly.
- 0.4.0: the aurora is a full-detail NumPy picture (emission added up, glow,
  tone mapping, lake reflection) made on the worker a little ahead of time;
  the render thread blends two consecutive pictures, so it is smooth on any
  renderer, and it never runs ahead of the pictures made.
- Preparations can be cancelled: the engine gives each scene context a
  `cancelled()` check (true once the engine closes or a newer scene is
  chosen), and long preparations call `Scene.checkpoint()` between steps.

## Failure handling

| Failure | Behaviour |
|---|---|
| No desktop / not allowed to connect | direct HDMI; if that fails too (no screen connected, no access to `/dev/dri`, the screen in use): standalone message + exit code 3; under mFruit OS LCD *No HDMI desktop* with Retry / Details / Back (no retry loop) |
| SDL2, NumPy or Pillow missing | `install.sh` fetches the Debian packages without root into the data folder; if that fails it refuses to install and names the apt command; at run time exit code 4 / LCD *Software missing* |
| No GPU renderer | SDL's software renderer (Balanced quality, half-size drawing on direct HDMI, a steady lower frame rate), noted in `--diagnose` |
| A scene raises | it is closed and reported; Minimal takes over |
| Saved screen not connected | shown on the first screen with a visible notice, never silently |
| Screen connected again | the window moves back to the saved screen |
| Settings file unreadable | kept as `settings.json.corrupt-<time>`, defaults used, notice shown |
| Settings cannot be written | notice; retried 30 s later, not in a loop |
| Exit request / SIGTERM | leaves within a frame; LCD focus released; exit code 0 |
| Desktop session ends | expected: SDL loses the X connection and the process ends, so mFruit OS returns to Home (NOT tested) |

## What is not here (yet)

- Several screens at once (different scenes per screen, mirroring): the
  display layer enumerates every screen and the window can move between them,
  but one window is drawn. See [display backends](DISPLAY_BACKENDS.md).
- Real-sky rendering (constellations for a location and time).
