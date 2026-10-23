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

## Session 2026-10-23 (2): refinement plan, Phase 1 done (0.3.0)

The owner's plan (pasted 2026-10-23) has three phases, one at a time, stopping
after each for review: (1) refine Galaxy (inside view), Nebula (slower), Aurora
(from below), Galaxy projector (realism); (2) propose, then build, a layer
system for backgrounds and add-on effects; (3) meteors as an add-on, then other
occasional objects (propose a list, wait for the owner's choice).

Phase 1 is IMPLEMENTED and AUTOMATED (205 tests; `tests/test_scene_views.py`),
measured on the board with a stand-in HDMI output because the monitor was
disconnected (docs/records/2026-10-23-phase1-scenes.md). Notes:

- Galaxy: `app/scenes/milkyway.py` (`InsideGalaxy`, default); the old view is
  `OutsideGalaxy` in `galaxy.py`, chosen by the new `galaxy_view` setting
  through `Scene.create(ctx)`.
- Aurora: GPUs draw ray meshes; the software renderer paints the curtains
  with NumPy (`SoftwareCurtains`), because SDL rasterises long diagonal
  triangles slowly. A test checks the two paths give the same picture.
- Concurrent edits appeared during this session (not made by this session):
  `noise.upsample`, `_field(..., shrink=)` and a cancellation check
  (`SceneContext.cancelled`, `Scene.checkpoint`, `Cancelled`, the engine's
  token). They were kept, tested (`test_scene_views.py`) and documented.
- Owner's standing priority (same day): **quality before speed**, motion smooth.
  Applied: Quality Auto = Balanced on the software renderer too; textures made at
  their drawn size; aurora painter at 0.5; tile-seam fix. Steady rates on the
  board are now 12-24 fps (record above). Keep this priority in Phases 2 and 3.
- Next: Phase 2 starts with a design proposal to the owner, no code first.

## Session 2026-10-22/23: device install, direct HDMI, smooth on the board (0.2.0)

Owner's requests, in order: (1) the Store install failed with exit code 1 on
the Orange Pi (cause: SDL2 missing; `install.sh` stopped as designed);
(2) "check for missing requirements and download/install them automatically,
and work without a desktop"; (3) on the 1 GB Orange Pi Zero 2W, slower,
smooth motion — fades rather than fast movement; (4) "no need for the solar
system; the meteor shower needs no moving objects; some scenes only need a
clear background and a bunch of stars fading in and out".

Done (IMPLEMENTED, AUTOMATED; board numbers in
docs/records/2026-10-23-board-hdmi-motion.md):

- `app/deps.py` + `install.sh`: missing SDL2/NumPy/Pillow fetched without root
  (`apt-get download` + `dpkg-deb -x` into `<data>/sysroot`, `env.sh` sourced by
  `run.sh`/`test.sh`). A root install from a hook was refused: mFruit OS ADR 0011.
- `app/display/kms.py`: direct HDMI through DRM/KMS when there is no desktop
  (`--output auto|desktop|hdmi`); half-size drawing + `SDL_SoftStretchLinear`.
- Motion setting (Auto = Gentle without a GPU); steady frame rate
  (`STEADY_RATES`); pacer fix (a late frame no longer adds a whole interval);
  software-renderer pre-scaling; galaxy composed with Pillow in the background.
- Scenes: **Starlight** added; **Solar system** and **Meteor shower** removed
  (`catalog.RETIRED` maps saved settings to Galaxy/Starlight); in gentle motion
  no meteors and the night sky and Minimal hold still. My reading of request (4);
  the owner may want something else.
- Version 0.2.0 (manifest, `app/__init__.py`, CHANGELOG). Not released: the
  owner commits, pushes and tags; then update MFruitOS `config/catalog.json`
  (version, url, sha256, description without "needs a desktop"; the
  `system_packages` list can stay or go now that install.sh fetches them).

Not verified: the picture on the board's monitor by eye; 0.2.0 launched from
mFruit OS Home on the board; package fetching on a real device lacking them.

## Status

| # | Step | Status |
|---|---|---|
| D1 | Audit of mFruit OS (app contract, SDK 1.5.0, lifecycle, daemon, installer); baseline `scripts/check.sh` green (781 tests) | DONE |
| D2 | SDL2 host: session discovery (env, loginctl, user processes, sockets; verified by connecting), window, displays (SDL + xrandr names), GPU/software renderer, events, full screen (desktop mode), cursor | IMPLEMENTED, AUTOMATED |
| D3 | Engine: 7 scenes (8 until 0.2.0), worker-thread preparation, cross-fades, rotation, pause, sleep timer, soft edges, failure fallback; quality presets | IMPLEMENTED, AUTOMATED |
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
3. Released and in the Fruit Store: v0.1.1 (the release workflow attached
   `mdisplay-0.1.1.tar.gz` + `SHA256SUMS`) is pinned in mFruit OS
   `config/catalog.json` (MFruitOS `f304151`); the hourly catalogue sync
   follows later releases. The hand-made v0.1.0 has no package (delete it on
   GitHub if wanted).
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
