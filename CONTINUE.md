# CONTINUE — mDisplay hand-off

Started 2026-10-22 at the owner's request: create **mDisplay** in
`/home/meng/mDisplay` from the "MFruit Galaxy" brief (animated galaxies, night
skies, nebulae, auroras, planets on an HDMI screen) as a genuine mFruit OS app.
App id `mdisplay`, name "mDisplay" (the owner named the project; the brief's
`mfruit-galaxy` id was not used). Nothing is committed: the owner commits.

## Decisions

- **Separate app repository**, like RadioConnect; mFruit OS itself is not changed.
- **Rendering: SDL2 through ctypes** (`app/display/sdl2.py`), the system
  `libSDL2` 2.0.18+. GPU renderer (OpenGL / OpenGL ES) when the desktop has
  one, SDL's software renderer otherwise. pygame was rejected after a
  prototype (whole-pixel positions, per-sprite calls, a big wheel); see
  docs/ARCHITECTURE.md.
- **Under mFruit OS** the Whisplay LCD is the remote control (SDK input and
  chrome, daemon contract); the scenes go to the desktop session's screen,
  which mDisplay finds itself. Run by hand it is the window alone, with an
  on-screen settings panel. One menu model drives both.
- Owner's mid-session request (2026-10-22): *every animation selectable on the
  mFruit device; display like a galaxy projector, without showing the screen's
  edges, with different options* →
  1. LCD **Scenes** list (hold on the remote's home): every scene, the one on
     screen marked; hold shows it; Settings is its last row.
  2. New scene **Galaxy projector** (turning nebula + laser stars, layers larger
     than the screen's diagonal) with options: colours (5 themes), lasers
     (green/red/both/off), turning (off/slow/medium/fast).
  3. **Soft edges** for every scene (off/soft/strong, default soft): the picture
     fades to black at the screen's border.
  Not done, and needing the owner's decision: one mFruit OS Home entry per
  scene (one manifest is one app; it would mean eight packages).

## Status

| # | Step | Status |
|---|---|---|
| D1 | Audit of mFruit OS (app contract, SDK 1.5.0, lifecycle, daemon, installer); baseline `scripts/check.sh` green (781 tests) | DONE |
| D2 | SDL2 host: session discovery (env, loginctl, user processes, sockets; verified by connecting), window, displays (SDL + xrandr names), GPU/software renderer, events, full screen (desktop mode), cursor | IMPLEMENTED, AUTOMATED |
| D3 | Engine: 8 scenes, worker-thread preparation, cross-fades, rotation, pause, sleep timer, soft edges, failure fallback; quality presets | IMPLEMENTED, AUTOMATED |
| D4 | Scenes incl. Galaxy projector | IMPLEMENTED, AUTOMATED; looks reviewed in GPU previews |
| D5 | Settings, HDMI panel, LCD remote incl. Scenes list | IMPLEMENTED, AUTOMATED |
| D6 | Package: manifest, hooks, icon, smoke test, release build, CI + release workflows | IMPLEMENTED; `check-app.py` passes; workflows not yet run on GitHub |
| D7 | mFruit OS integration against the REAL daemon + launcher (sideload, launch, Scenes list and Settings by button, exit, relaunch, force stop, uninstall) | AUTOMATED (`tests/test_mfruitos_integration.py`) |
| D8 | Live desktop on this Jetson (X11 :1, DP-0, 1920×1080@144): window and full screen OBSERVED, ~60 fps at 1080p; 10-minute soak flat; suite green in an Ubuntu 22.04 root | DONE, docs/records/2026-10-22-first-validation.md. Keys from a real keyboard NOT VERIFIED |
| D9 | Docs, CHANGELOG | DONE (README, docs/*.md) |

## Next (owner)

1. Look at it: `cd ~/mDisplay && ./run.sh --windowed` (Esc closes), then `./run.sh`
   for full screen; `→`/`←` scenes, `B` settings, `F11`, `Esc`: this is also the
   keyboard check I could not do (live checklist in docs/TESTING.md).
2. Decide: keep the name/id `mdisplay` (permanent after the first release).
3. Commit and push to `github.com/Mengkungkao/mDisplay` (created by the owner,
   README committed); pushing `manifest.json` lets the release workflow publish
   v0.1.0 (docs/RELEASING.md). Optionally the Fruit Store entry.
4. On a board with a desktop on HDMI: sideload and run the device checklist in
   docs/TESTING.md.

## Not verified

- A physical HDMI connection (this machine's monitor is on DisplayPort DP-0).
- A Whisplay board with a desktop on its HDMI port (no such setup here).
- Wayland sessions (only X11 is available here; Wayland code is unit-tested).
- Python 3.9 at run time (syntax checked; 3.10 ran the whole suite in an Ubuntu 22.04 root).
- Keys typed on a real keyboard into the window.

## Known limitations

- Up to ~150 ms hitches while the next scene is prepared (worker thread vs the GIL).
- Aurora is the most expensive scene (5–11 ms CPU per frame at 1080p here).
- On the software renderer the projector's clouds drift instead of turning.
