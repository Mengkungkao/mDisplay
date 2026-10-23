# Troubleshooting

Start with the report: it checks everything for real and says what to do.

```bash
./run.sh --diagnose          # or --diagnose --json
```

Under mFruit OS the app's output is in `~/.whisplay-os/logs/mdisplay.log`
(run it with `~/.whisplay-os/apps/mdisplay/current/run.sh --diagnose` over SSH
for the report). Exit codes: 0 normal, 2 bad command line, 3 no usable
desktop/screen, 4 missing software, 1 other failure.

## "No desktop session was found: this computer looks headless"

No X server or Wayland compositor runs for this user. mDisplay needs a logged-in
desktop on the HDMI screen (it does not take over the console). Log in to the
desktop as the same user mFruit OS runs as (or that runs `run.sh`), then Retry.
On Raspberry Pi OS Lite or a server image there is no desktop; installing one
(and auto-login, if wanted) is outside mDisplay.

## "A desktop session exists but mDisplay may not open it"

`--diagnose` lists every candidate and why it failed. Usual causes:

- **X11, another user's session.** The X server belongs to someone else, or
  its cookie (`XAUTHORITY`) is not readable. Run mDisplay as the desktop's user.
- **X11, cookie in an unusual place.** mDisplay looks in the environment of
  your own session processes, `/run/user/<uid>/gdm/Xauthority`,
  `~/.Xauthority` and XWayland's `/run/user/<uid>/.mutter-Xwaylandauth.*`.
  Point it at a display explicitly: `run.sh --session :0` (with `XAUTHORITY`
  set), or `MDISPLAY_SESSION=:0`.
- **Wayland only (no XWayland).** mDisplay connects to the compositor's socket
  in `XDG_RUNTIME_DIR`; under a system service that directory must be the
  user's (`/run/user/<uid>`). `run.sh --session wayland-0` forces it.
- **The selected session does not exist.** An explicit `--session` is never
  replaced by another one: fix the value or remove it.

## Black window, or the picture on the wrong screen

- `./run.sh --list-displays` shows the screens and their keys; choose one in
  Settings → Screen or with `--display HDMI-1`. If the saved screen is
  missing, mDisplay shows a notice and uses the first screen; when the saved
  screen comes back it moves there by itself.
- Some compositors take a moment to map a full-screen window on another
  screen; press F11 twice.

## Slow, or "Only software rendering is available"

SDL found no working OpenGL or OpenGL ES driver for this desktop. mDisplay
then uses SDL's software renderer: it works, at a lower but steady frame rate
(choose quality Eco for more frames).
Check the GPU driver (`glxinfo -B` on X11), or try `--renderer opengles2`.
`I` shows the frame rate and renderer on screen.

## "SDL … is too old" / "the SDL2 library was not found"

`sudo apt install libsdl2-2.0-0`. SDL 2.0.18 or newer is required (Debian 12,
Ubuntu 22.04, Raspberry Pi OS Bookworm and newer have it; Debian 11 has
2.0.14). `MDISPLAY_SDL2=/path/to/libSDL2-2.0.so.0` uses another copy.

## Keys do nothing

- Under mFruit OS the keyboard belongs to mFruit OS, which forwards keys to
  the app on the LCD. Keys work while mDisplay is the app on the LCD.
- On a desktop the window must have keyboard focus (click it).

## The screen blanks or never blanks

While scenes run, SDL keeps the desktop's screen saver away (only while
mDisplay runs). Setting *Screen blanking* on allows it anyway; while paused or
after the sleep timer it is always allowed. mDisplay never changes power or
brightness settings of the system.

## Settings were reset

The file could not be read; the old one is beside it as
`settings.json.corrupt-<time>` ([configuration](CONFIGURATION.md)).

## X11 and Wayland notes

| | X11 (incl. XWayland) | Wayland |
|---|---|---|
| Used when | `DISPLAY` works (preferred: SDL 2 is most mature there) | only a Wayland socket works |
| Screen names | X11 output names (`HDMI-1`, `DP-0`) via `xrandr` | SDL's names (`display-N` keys) |
| Full screen | desktop full screen on the chosen output | compositor decides placement; some compositors ignore the requested output |
| Verified here | yes (GNOME on Xorg, Jetson) | not on a live session |
