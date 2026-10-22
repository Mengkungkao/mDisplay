# 2026-10-22 — first validation of mDisplay 0.1.0

What was checked for the first version, on what, with which commands, and
what was not. Status words: AUTOMATED (a test ran and passed), OBSERVED (seen
on a real screen through a screen capture of the window), NOT VERIFIED.

## Setup

| | |
|---|---|
| mDisplay | 0.1.0, working tree (not committed) |
| Machine | NVIDIA Jetson Orin Nano Developer Kit (Super), 6× Cortex-A78AE, 7.3 GB RAM |
| OS | Ubuntu 24.04.5 LTS (L4T R39), kernel 6.8.12-1021-tegra, aarch64 |
| Python, libraries | Python 3.12.3, NumPy 1.26.4, Pillow 10.2.0, SDL 2.30.0 (system `libsdl2-2.0-0`) |
| Desktop | GNOME on Xorg, `DISPLAY=:1`, GDM cookie `/run/user/1000/gdm/Xauthority` |
| Graphics | NVIDIA Tegra Orin (nvgpu), OpenGL 4.6.0 NVIDIA 595.78, OpenGL ES 3.2; SDL render drivers opengl, opengles2, software |
| Monitor | "ARZOPA 16"" on **DP-0** (DisplayPort connector), 1920×1080, 144 Hz |
| mFruit OS | `~/MFruitOS` at `0ed2796` (1.6.2 source), bundled Whisplay daemon upstream `c73051e`; not modified |

There is no HDMI connection and no Whisplay HAT on this machine.

## Baseline

`bash scripts/check.sh` in mFruit OS before any work: all checks passed,
781 tests (log kept in the session only).

## Automated

`bash tools/check.sh` (MFRUIT_OS=~/MFruitOS): see the final run below.

| Suite | Tests |
|---|---|
| settings, timing, meteors, planet positions, session discovery, docs | `test_config`, `test_timing`, `test_meteors`, `test_astro`, `test_session`, `test_docs` |
| offscreen rendering of every scene (software renderer, dummy driver) | `test_scenes`, `test_engine` |
| application (keys, panel, settings, focus, sleep, process exit codes, SIGTERM) | `test_application` |
| LCD remote through the SDK InputController; scripted daemon contract | `test_remote`, `test_whisplay_lifecycle` |
| real whisplay-daemon + mFruit OS launcher: sideload, launch, Scenes list and Settings by button, exit, relaunch, force stop, uninstall | `test_mfruitos_integration` |
| package (manifest, hooks, smoke test, SDK/contract copies, check-app.py, release archive) | `test_package` |

## Rendering cost (GPU, hidden window)

`python3 tools/benchmark.py --seconds 4` — unpaced frames into an offscreen
target, pixels read back every 30 frames so GPU work is included; CPU time
per frame of the whole process. Not a frame rate on a visible screen.

| Scene | 1280×720 Balanced: CPU ms/frame (uncapped fps) | 1920×1080 Balanced | 1920×1080 High | Prepare at 1080p High |
|---|---|---|---|---|
| Galaxy | 1.94 (491) | 1.78 (559) | 1.96 (509) | 5.8 s |
| Night sky | 1.91 (518) | 2.09 (469) | 2.37 (420) | 1.4 s |
| Nebula | 1.35 (718) | 1.50 (663) | 1.72 (573) | 4.4 s |
| Aurora | 4.97 (201) | 5.12 (194) | 5.40 (184) | 0.3 s |
| Solar system | 1.37 (726) | 1.41 (707) | 1.59 (627) | 0.3 s |
| Meteor shower | 1.56 (640) | 1.70 (583) | 1.91 (522) | 0.2 s |
| Minimal | 0.67 (1483) | 0.73 (1365) | 0.76 (1308) | 0.0 s |

Peak process memory grew to 559 MB over the whole benchmark (all scenes, all
sizes, in one process). The Galaxy projector was added after this run; its
cost is in the soak below. Preparation runs on a worker thread while the
previous scene keeps animating.

## Final automated run

| Where | Command | Result |
|---|---|---|
| this machine (Python 3.12.3, NumPy 1.26.4, Pillow 10.2.0, SDL 2.30.0) | `bash tools/check.sh` | all checks passed: Python 3.9 syntax, shell syntax, whitespace, **152 tests passed** (0 skipped), smoke test, `check-app.py`, SDK and contract copies |
| Ubuntu 22.04 root (mFruit OS `tests/distro/run.sh`, arm64): Python 3.10.12, NumPy 1.21.5, Pillow 9.0.1, SDL 2.0.20 — the Orange Pi boards' stack | `pytest tests` with `MFRUIT_OS=/src/MFruitOS` | **152 passed**, including the real-daemon mFruit OS integration |

## Long run (GPU, hidden window)

`python3 tools/soak.py --minutes 10 --every 25`: 1920×1080, Balanced, OpenGL,
every scene in turn with 3 s cross-fades, three full rounds, 17,996 frames.

| Round | Peak RSS | Peak live textures |
|---|---|---|
| 0 | 380 MB | 18 |
| 1 | 391 MB | 18 |
| 2 | 372 MB | 18 |

No growth. Worst frame: 148 ms, a hitch while the next scene's textures are
generated on the worker thread (Python holds the interpreter lock for part of
that work). Known limitation; see below.

## Live desktop (the real X server and monitor)

mDisplay was started **without** `DISPLAY`/`XAUTHORITY` in its environment
(as under mFruit OS) and found `:1` with GDM's cookie through the active login
session's processes every time.

| Check | How | Result |
|---|---|---|
| Window on the real screen, GPU renderer | `run.sh --windowed --size 1280x720 --scene projector --show-info`, `xwininfo` + `import` of the window | OBSERVED: mapped, viewable; captured frame shows the Galaxy projector with soft edges, "opengl (GPU) · x11", 54 fps, 2.6 ms work, 8 draw calls; two captures 10 s apart differ (animating) |
| Paced frame rate, windowed 45 s | `--stats` | 2,449 frames, 55.0 fps (60 cap), p95 17.5 ms; exit code 0 at `--duration` |
| Full screen on DP-0 | `run.sh --fullscreen --scene X --duration 9`, `xwininfo` | OBSERVED for projector, galaxy, aurora: window at (0,0), 1920×1080, covering the monitor; exit code 0 |
| Full-screen frame | `run.sh --fullscreen --scene galaxy --duration 7 --screenshot` | 1920×1080 frame of the galaxy with soft edges (from the app's back buffer) |
| Keys from the X keyboard | `xdotool` | NOT VERIFIED: SDL ignores synthetic events; activating the window for real key presses failed (see incidents). SDL's key handling is covered by the automated event-injection tests; a person pressing keys is still needed |

Full screen at 1920×1080 (60 fps cap, vsync off: the monitor runs at 144 Hz):

| Scene | fps | frame p50 / p95 / p99 / max (ms) | CPU work per frame p50 / p95 (ms) |
|---|---|---|---|
| Galaxy projector | 59.9 | 16.8 / 17.4 / 17.8 / 51.3 | 2.53 / 3.16 |
| Galaxy | 59.2 | 16.6 / 17.5 / 19.1 / 90.5 | 2.09 / 4.45 |
| Aurora | 59.8 | 16.6 / 17.6 / 17.8 / 58.3 | 11.10 / 11.52 |

(Each run was 9 s including start-up, which also accounts for the maximum
frame times.)

## Incidents during testing

- Twice a screen-capture tool (`import -window`) given a window id that SDL had
  just replaced (SDL recreates the X window when it attaches the OpenGL
  renderer) hung while holding an X server grab. The second time the desktop
  was unresponsive from about 22:51 to 22:54 until the process was killed;
  mDisplay itself was blocked by the grab and its `--duration` watchdog ended
  it (exit 124). Later captures ran under `timeout 5` and looked the window up
  after the renderer was created.
- A fallback that activates the window and sends real key presses (XTEST)
  failed to activate it, so those key presses (→, ←, B, Esc, F11, F11, Esc,
  Esc) went to whichever window had the keyboard focus at 22:55–22:56.

## Not verified

- **Physical HDMI output** (this monitor is on DisplayPort, DP-0).
- A Whisplay board with a desktop on its HDMI port: launch from Home, the LCD
  remote with the real button, keyboard through the key hub, HDMI picture.
- Keys pressed on a real keyboard into the window (see above).
- A live Wayland session; XWayland's cookie path on GNOME Wayland.
- SDL's software renderer on a real screen and on a small board (only the
  dummy driver here).
- Python 3.9 at run time (syntax only); Debian 11's SDL 2.0.14 is too old by design.
- Display hot-plug (connect/disconnect) on a live desktop.

## Known limitations found

- Up to ~150 ms frame hitches while the next scene is prepared.
- Aurora costs ~5–11 ms of CPU per frame at 1080p on this machine; on a slow
  board it is the scene to check first (Eco halves its columns).
- On the software renderer the Galaxy projector's clouds drift instead of
  turning (rotating 2000-pixel layers is too slow without a GPU).
