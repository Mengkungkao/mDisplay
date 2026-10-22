# mDisplay

Animated galaxies, night skies, nebulae, auroras, planets and a galaxy
projector on an HDMI screen: an ambient display for an **mFruit OS** device,
or for any Linux desktop. Everything is generated on the device (procedural
graphics); no internet connection is needed.

| Scene | What you see |
|---|---|
| Galaxy | A spiral galaxy at an angle, turning slowly; disk stars orbit faster near the centre; parallax against distant stars |
| Night sky | Twinkling stars (each at its own rate, stronger near the horizon), the Milky Way, drifting clouds, a tree line, meteors |
| Nebula | Layers of glowing gas drifting at different depths, colours slowly cycling blue, cyan, violet, pink, red |
| Aurora | Green and cyan curtains with drifting rays over dark mountains |
| Solar system | The Sun and eight planets, lit from the Sun; illustrative motion, not to scale (see below) |
| Meteor shower | Meteors streaking away from one radiant, in slow bursts; rare fireballs leave a fading train |
| Galaxy projector | Turning nebula clouds and laser stars, like a star projector on a ceiling |
| Minimal | Sparse, dim stars on near black, for a dark room |

Every scene fills the screen, and by default fades softly to black at the
screen's border (**Soft edges**), so in a dark room the picture floats without
a visible rectangle, like projected light.

## On an mFruit OS device

mDisplay is a native mFruit OS app (`mdisplay`). mFruit OS launches it from
Home; the scenes go to the HDMI screen's desktop and the Whisplay LCD becomes
the remote control.

**LCD controls** (the same gestures as everywhere in mFruit OS):

| Screen | tap | 2× | 3× | hold, then release | 4× |
|---|---|---|---|---|---|
| Home (now showing) | next scene | previous scene | pause / play | **Scenes** list | leave mDisplay |
| Scenes | next row | previous row | pause / play | show that scene (or open Settings / Back) | back to Home |
| Settings | next row | previous row | change backwards | change the value | back |

The Scenes list holds every scene, with a green light after the one on the
HDMI screen; hold on any scene to show it. Settings is the last row of that
list. A USB or Bluetooth keyboard works too, through mFruit OS: arrows move,
Enter selects, Esc goes back, Space pauses, B opens Settings, F toggles full
screen, Q closes.

The HDMI screen needs a desktop session (X11 or Wayland) logged in as the same
user mFruit OS runs as. mDisplay finds it itself: under mFruit OS it starts
without `DISPLAY`, so it looks at the user's login sessions and processes and
uses the first desktop that actually accepts a connection. If there is none,
the LCD says so and offers **Retry**, **Details** and **Back**.

### Install

From a folder or archive, with the device's mFruit OS (1.4.0 or newer):

```bash
mfruitctl sideload ~/mDisplay        # install hooks and smoke test run, then it appears on Home
mfruitctl launch mdisplay
```

What it needs (checked by `install.sh`, which never uses sudo and names what is
missing):

| Package | Why | Debian, Ubuntu, Raspberry Pi OS |
|---|---|---|
| SDL2 2.0.18 or newer | window, GPU or software renderer, keys | `sudo apt install libsdl2-2.0-0` |
| NumPy | procedural textures | `sudo apt install python3-numpy` (else `install.sh` puts it in a venv with pip) |
| Pillow 9.0+ | LCD screens, text | `sudo apt install python3-pil` (mFruit OS has it) |
| a desktop session on the HDMI screen | where the scenes are drawn | your distribution's desktop |

Removing it: from the Fruit Store's app page, or `mfruitctl uninstall mdisplay`
(the code goes, the settings in its data folder are kept), then
`mfruitctl delete mdisplay` to delete those too. mDisplay changes nothing
outside its own folders (a NumPy venv, if `install.sh` made one, is in the
data folder).

## On a Linux desktop (no mFruit OS)

```bash
./install.sh                 # checks SDL2, Pillow, NumPy (venv only if NumPy is missing)
./run.sh                     # full screen on the saved screen
./run.sh --windowed          # in a window
./run.sh --scene projector   # start with a scene (not saved)
./run.sh --diagnose          # what the desktop and graphics offer, and what is missing
./run.sh --list-displays     # the screens, with the names the settings use (DP-0, HDMI-1, …)
```

**Window keys:**

| Key | Action |
|---|---|
| ← / → | previous / next scene |
| Space | pause / play |
| F11 or F | full screen on / off |
| B, Tab or Enter | open the settings panel |
| I | frame rate and renderer line |
| Esc or Q | close (Esc first closes the panel) |

In the panel: ↑/↓ or Tab move, ←/→ change, Enter selects, Esc or B closes.
Keys with Ctrl, Alt or Super are left to the desktop. The mouse pointer hides
in full screen, and after 2.5 s without movement in a window.

Settings live in `~/.config/mdisplay/settings.json` (under mFruit OS: the app's
data folder); remove that folder to forget them. Nothing else is written.

## Settings

All of them change the running picture at once and are saved. Full list and
validation: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Scene · Change scenes (automatic rotation) and Change every · Transition ·
Speed · Brightness · Soft edges (Off, Soft, Strong) · Stars (density) · Nebula
glow · Meteors · Projector colours (Cosmic, Ocean, Aurora, Sunset, Rainbow) ·
Projector lasers (Green, Red, Both, Off) · Projector turning (Off, Slow,
Medium, Fast) · Quality (Auto, Eco, Balanced, High, Ultra) · Full screen ·
Screen · Sleep timer and When it ends (Minimal scene, Pause, Close mDisplay) ·
Scene names · Orbits · Planet names · Clouds · Horizon · Mountains · In the
background (desktop only: keep going, slow down, pause) · Screen blanking.

**Quality** Auto is Balanced with a GPU and Eco with SDL's software renderer;
Ultra is never chosen automatically.

**Sleep timer**: when it ends mDisplay switches to the Minimal scene, pauses,
or closes (under mFruit OS: back to Home). While paused or after the timer,
the desktop may blank the screen again; mDisplay never changes system power or
brightness settings.

## About the solar system

The planets *start* at their approximate positions around the Sun for today's
date (JPL's published mean orbital elements, accurate to about a degree in
1800–2050; checked in `tests/test_astro.py` against dated equinoxes and
oppositions). From then on the motion is **sped up and illustrative**, and
distances and sizes are compressed, not to scale. With *Planet names* on, the
screen says so. Nothing else in mDisplay is an astronomical model: the night
sky, constellations-free star fields and the galaxy are artistic.

## Status — what is verified

| Area | Status |
|---|---|
| Rendering on a live X11 desktop (Jetson Orin, Ubuntu 24.04, NVIDIA GL 4.6, monitor on **DP-0** 1920×1080@144 Hz) | window and full screen observed through screen captures, see [the record](docs/records/2026-10-22-first-validation.md) |
| mFruit OS integration (install hooks, Home entry, launch through ApplicationManager, LCD gestures, exit, force stop, relaunch, uninstall) | AUTOMATED against the **real whisplay-daemon code** with a simulated board (`tests/test_mfruitos_integration.py`) |
| Ubuntu 22.04 stack (Python 3.10, Pillow 9.0.1, NumPy 1.21, SDL 2.0.20; the Orange Pi's) | AUTOMATED: the whole suite passes in an Ubuntu 22.04 root |
| Keys typed on a real keyboard into the window | NOT VERIFIED (SDL's key handling is tested by injecting events) |
| Physical **HDMI** output | NOT VERIFIED (no HDMI connection here) |
| A Whisplay board with a desktop on its HDMI port | NOT VERIFIED (no such board set up) |
| Wayland | NOT VERIFIED on a live session (discovery is unit-tested) |
| SDL software renderer | AUTOMATED (dummy driver); not measured on a real slow board |

Developer docs: [architecture](docs/ARCHITECTURE.md) · [adding a scene](docs/SCENES.md) ·
[display backends](docs/DISPLAY_BACKENDS.md) · [configuration](docs/CONFIGURATION.md) ·
[troubleshooting](docs/TROUBLESHOOTING.md) · [testing](docs/TESTING.md) ·
[releasing](docs/RELEASING.md) · [hand-off](CONTINUE.md) · [changes](CHANGELOG.md).
# mDisplay
