# mDisplay

Animated galaxies, night skies, nebulae, auroras and starlight on an HDMI
screen: an ambient display for an **mFruit OS** device,
or for any Linux desktop. Everything is generated on the device (procedural
graphics); no internet connection is needed.

| Scene | What you see |
|---|---|
| Galaxy | From inside the galaxy, like a dark-sky photograph: the Milky Way's band across the sky, warmer and denser towards the core, broken by dark dust lanes, drifting slowly; stars at three depths (parallax). *Galaxy view: Outside* shows the earlier spiral galaxy turning, seen at an angle |
| Night sky | Twinkling stars (each at its own rate, stronger near the horizon), the Milky Way, drifting clouds, a tree line, meteors |
| Nebula | Layers of glowing gas drifting at different depths, colours slowly cycling blue, cyan, violet, pink, red (half the 0.2 speed; slower again in Gentle motion) |
| Aurora | A great aurora over a lake, as in a long-exposure photograph: curtains sweeping across the sky with fine rays fanning towards the zenith, bright yellow-green low down, pink and magenta higher, lavender-white where they overlap, teal on the right, thin violet streaks high up; stars through it, a dark treeline of islands and the lake reflecting the light |
| Starlight | A clear dark sky where stars slowly fade in, shine and fade out, then return elsewhere; nothing moves |
| Minimal | Sparse, dim stars on near black, for a dark room |

Every scene fills the screen, and by default fades softly to black at the
screen's border (**Soft edges**), so in a dark room the picture floats without
a visible rectangle, like projected light.

**Motion** (Auto, Full, Gentle): on a board without a GPU, where only a few
frames a second can be drawn, Auto chooses *Gentle*: nothing travels across
the sky (no meteors; the night sky and Minimal hold still), stars twinkle more
slowly, and what does move (galaxy, gas, curtains) moves more
slowly. mDisplay also settles on a steady frame rate the board keeps up with,
because an even rhythm looks smoother than a faster, uneven one.

## On an mFruit OS device

mDisplay is a native mFruit OS app (`mdisplay`). mFruit OS launches it from
Home; the scenes go to the HDMI screen and the Whisplay LCD becomes the remote
control.

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

**No desktop needed.** When no desktop session runs on the device (the usual
mFruit OS setup), mDisplay drives the HDMI port itself through Linux DRM/KMS,
draws with SDL's software renderer at half the screen's resolution and scales
each frame up once (1280×720 is chosen when the screen offers it). The user
needs access to `/dev/dri/card*` (the `video` group, as on Orange Pi and
Raspberry Pi images), and nothing else may be showing on HDMI at the time.
When a desktop session (X11 or Wayland) *is* running as the same user, mDisplay
finds it and uses it instead, with the GPU when there is one. If neither works,
the LCD says why and offers **Retry**, **Details** and **Back**.

### Install

From a folder or archive, with the device's mFruit OS (1.4.0 or newer):

```bash
mfruitctl sideload ~/mDisplay        # install hooks and smoke test run, then it appears on Home
mfruitctl launch mdisplay
```

What it needs: SDL2 2.0.18 or newer, NumPy and Pillow 9.0+. `install.sh`
checks them and, when one is missing, **fetches it itself without root**: it
downloads the Debian packages (and what they depend on) with `apt-get
download` from the device's own apt sources and unpacks them into mDisplay's
data folder (`sysroot/`), which `run.sh` adds to the library and Python paths.
Nothing outside that folder changes. It needs a network connection the first
time; if fetching fails, the install stops and says what to run once instead
(`sudo apt install libsdl2-2.0-0 python3-numpy python3-pil`).

Removing it: from the Fruit Store's app page, or `mfruitctl uninstall mdisplay`
(the code goes, the settings in its data folder are kept), then
`mfruitctl delete mdisplay` to delete those too, with any packages `install.sh`
fetched. mDisplay changes nothing outside its own folders.

## On a Linux desktop (no mFruit OS)

```bash
./install.sh                 # checks SDL2, Pillow, NumPy; fetches what is missing, no root
./run.sh                     # full screen on the saved screen
./run.sh --windowed          # in a window
./run.sh --scene aurora      # start with a scene (not saved)
./run.sh --output hdmi       # straight to the HDMI port (DRM/KMS), no desktop
./run.sh --diagnose          # what the desktop, HDMI and graphics offer, and what is missing
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
Speed · Motion (Auto, Full, Gentle) · Brightness · Soft edges (Off, Soft,
Strong) · Stars (density) · Nebula glow · Meteors · Galaxy view (Inside,
Outside) · Quality (Auto, Eco, Balanced, High, Ultra) · Full screen · Screen ·
Sleep timer and When it ends (Minimal scene, Pause, Close mDisplay) · Scene
names · Clouds · Horizon (night sky) · Mountains (the aurora's lake and shore) ·
In the background (desktop only: keep going, slow down, pause) · Screen
blanking.

**Quality** Auto is Balanced, with a GPU or without one: picture quality comes
before frame rate, and on a small board mDisplay settles on a lower but steady
frame rate instead. Eco is there for a board that should work less; Ultra is
never chosen automatically.

**Sleep timer**: when it ends mDisplay switches to the Minimal scene, pauses,
or closes (under mFruit OS: back to Home). While paused or after the timer,
the desktop may blank the screen again; mDisplay never changes system power or
brightness settings.

The scenes are artistic, not astronomical models.

## Status — what is verified

| Area | Status |
|---|---|
| Rendering on a live X11 desktop (Jetson Orin, Ubuntu 24.04, NVIDIA GL 4.6, monitor on **DP-0** 1920×1080@144 Hz) | window and full screen observed through screen captures, see [the record](docs/records/2026-10-22-first-validation.md) |
| mFruit OS integration (install hooks, Home entry, launch through ApplicationManager, LCD gestures, exit, force stop, relaunch, uninstall) | AUTOMATED against the **real whisplay-daemon code** with a simulated board (`tests/test_mfruitos_integration.py`) |
| Ubuntu 22.04 stack (Python 3.10, Pillow 9.0.1, NumPy 1.21, SDL 2.0.20; the Orange Pi's) | AUTOMATED: the whole suite passes in an Ubuntu 22.04 root |
| Keys typed on a real keyboard into the window | NOT VERIFIED (SDL's key handling is tested by injecting events) |
| Direct HDMI (DRM/KMS) on an Orange Pi Zero 2W (1 GB, Ubuntu 22.04, no desktop) | Run on the board on HDMI-A-1 at 1280×720: page flips completed and frame times were measured (every scene, see [the record](docs/records/2026-10-23-board-hdmi-motion.md)); the picture on the monitor NOT VERIFIED by eye |
| DRM ioctl numbers and structures | AUTOMATED against the Linux UAPI headers |
| Fetching missing packages without root | AUTOMATED with stand-in apt/dpkg commands, and run in an Ubuntu 22.04 root |
| A desktop session on a board's HDMI port | NOT VERIFIED (no such board set up) |
| Wayland | NOT VERIFIED on a live session (discovery is unit-tested) |

Developer docs: [architecture](docs/ARCHITECTURE.md) · [adding a scene](docs/SCENES.md) ·
[display backends](docs/DISPLAY_BACKENDS.md) · [configuration](docs/CONFIGURATION.md) ·
[troubleshooting](docs/TROUBLESHOOTING.md) · [testing](docs/TESTING.md) ·
[releasing](docs/RELEASING.md) · [hand-off](CONTINUE.md) · [changes](CHANGELOG.md).
