# Display backends

Today there are two, both drawn by SDL's renderer through
`app/gfx/canvas.py`:

- an SDL2 window on the desktop session's screen (`app/display/desktop.py`);
- **direct HDMI** (`app/display/kms.py`) when no desktop session runs: SDL's
  software renderer draws into a hidden window on SDL's `dummy` driver, and
  `DesktopDisplay.scan_out` copies each frame into a DRM dumb buffer that is
  page-flipped on the HDMI connector (legacy KMS ioctls through ctypes, no
  libdrm). Modes 1280 wide or more are drawn at half size and scaled up once
  with `SDL_SoftStretchLinear` (about 10 ms a frame on a Cortex-A53, against
  25 ms for a scaled `RenderCopy`).

`--output auto` (the default) uses a desktop when one accepts a connection and
direct HDMI otherwise; `--output hdmi` or `desktop` forces one. Direct HDMI is
automatic because mFruit OS devices normally have no desktop and the screen is
otherwise only showing the console. It takes DRM master on the first card with
a connected external connector (HDMI, DisplayPort, DVI, VGA; never a built-in
panel), keeps the CRTC's previous state and restores it on exit, so the console
comes back. The user needs access to `/dev/dri/card*` (the `video` group).
whisplay-daemon's LCD is on SPI, not DRM, so the two do not meet. This page says what a backend must provide, how the
current one does it, and how to add or improve one.

## The contract

The application uses a display for:

| Need | `DesktopDisplay` |
|---|---|
| open, or explain why not (`DisplayUnavailable(problem, remedy)`) | `open()` |
| the drawing surface | `.canvas` (a `gfx.canvas.Canvas`) and `.size` |
| screens: name, position, size, refresh | `list_displays()` → `DisplayInfo` |
| full screen without a mode change; choose a screen | `set_fullscreen()`, `move_to(key)` |
| events: keys, resize, expose, focus, minimise, close, screens added/removed, renderer reset | `events(timeout)` (decoded `sdl2.Event`s) |
| being woken from another thread | `wake()` |
| cursor, screen saver, vertical sync | `show_cursor()`, `allow_screensaver()`, `set_vsync()` |
| release everything | `close()` |

Scenes never see the backend: they only get a `Canvas`. A new backend
either provides an SDL renderer (then `Canvas` works unchanged) or a class
with the same methods as `Canvas` (`texture`, `target`, `into`, `clear`,
`fill`, `image`, `geometry`, `read_rgba`, `present`, `width`, `height`,
`accelerated`, `max_texture`, `screen_blend`, `live_textures`).

## Improving the SDL backend

- New SDL functions go into `_SIGNATURES` in `app/display/sdl2.py` with their
  exact C types. Check the SDL version that introduced them against
  `MIN_VERSION` (2.0.18) and raise the minimum, with a note in the README's
  requirements, if needed.
- Renderer selection is in `_create_renderer`: GPU drivers in SDL's order, then
  `software`; `--renderer` forces one. Failures are kept in `.attempts` and
  shown by `--diagnose`.
- Display names: SDL's name (often the monitor model) plus, on X11, the
  output name from `xrandr` matched by position and size. On Wayland SDL's
  name is used; a Wayland output-name lookup would go in `list_displays`.

## Possible backends (PLANNED, not implemented)

| Backend | When | Notes |
|---|---|---|
| Hardware scaling on a DRM plane | direct HDMI on a board whose display engine can scale (Allwinner DE, VC4) | the half-size frame on an overlay plane scaled by the display hardware would save the ~10 ms software stretch per frame; needs `SETPLANE` and per-driver testing |
| Several windows | different scenes per screen, or mirroring | one `DesktopDisplay` and `Engine` per screen; the application loop would wait on all of them. The settings would need a per-screen scene. Not claimed today. |
| The Whisplay LCD itself | a board without HDMI | scenes could render into a 240×280 target and be sent as RGB565 frames to the daemon; the remote would then need another screen layout. |

Any new backend comes with its own tests (offscreen where possible), a
`--diagnose` section, and a line in the README's status table that says
whether it was seen working on real hardware.
