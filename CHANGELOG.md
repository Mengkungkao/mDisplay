# Changelog

Versions follow the manifest. Each section becomes the GitHub release notes.

## [0.4.0] - 2026-10-23

- **Aurora, made realistic** after the owner's reference photographs: a great
  display over a lake. Curtains sweep across the sky with fine rays fanning
  towards the zenith; bright yellow-green low down, pink and magenta higher,
  lavender-white where they overlap, teal where a curtain is less red, thin
  violet streaks high up; stars shine through; a dark treeline of islands and
  a hill closes the horizon and the lake reflects the light (Mountains
  setting; off shows the sky only). The light is added up as emission, given
  a soft glow and tone-mapped like a photograph. Each picture is a
  full-detail NumPy render made on the worker thread; the render thread
  blends two consecutive pictures, so the motion stays smooth: 24 fps steady
  on the Orange Pi Zero 2W (it was 12), 0.42 s per picture there.
- **Removed: Galaxy projector.** A saved setting naming it shows the Nebula;
  its settings (colours, lasers, turning) are dropped.

## [0.3.0] - 2026-10-23

Phase 1 of the owner's refinement plan: the existing scenes, refined.

- **Galaxy, seen from inside**: the Milky Way's band across the sky, as in a
  dark-sky photograph: star clouds, a warmer and denser glow towards the core,
  a broken dark rift and dust clouds, faint pink star-forming regions, stars at
  three depths drifting at slightly different rates. The band drifts slowly
  sideways (smoothly below a pixel a second on the software renderer). The
  previous view stays as **Galaxy view: Outside** (new setting `galaxy_view`,
  default Inside).
- **Nebula**: half the 0.2 drift and colour-cycle speed in Full motion, slower
  again in Gentle; the values are named constants (`DRIFT`,
  `COLOR_CYCLE_SECONDS` in `app/scenes/nebula.py`).
- **Aurora, seen from below**: curtains overhead whose rays converge on a
  corona near the top of the screen, bunched into folds, stars visible between
  them; the mountains became a thin horizon at the bottom edge.
- **Galaxy projector**: softer, uneven clouds with empty patches, fine wisps at
  their edges and some colour variation inside; tiny, sharp laser stars of
  uneven brightness with a faint shimmer; a lens's fall-off and larger, softer
  points towards the edges.
- A scene's preparation now stops when the app closes or another scene is
  chosen, so quitting never waits for a long preparation.
- **Quality before frame rate** (the owner's priority): Quality *Auto* is now
  Balanced without a GPU too (more stars, more layers), and on the software
  renderer the nebula, Milky Way, clouds, projector clouds and outside galaxy
  are made at the size they are drawn instead of being scaled up; the aurora is
  painted at twice the area. The steady frame rate settles lower instead.
- Fixed: on the software renderer a faint bright line could show where two
  tiles of a drifting layer met (rectangles left of the screen were truncated
  towards zero); tiles are now placed on whole pixels.
- Measured on the Orange Pi Zero 2W with a stand-in HDMI output (the monitor
  was disconnected), Balanced quality: Galaxy 24 fps (outside view 20), Night
  sky 15, Nebula 15, Aurora 12, Starlight 24, projector 15, Minimal 24; every
  scene's frame times within about 1 ms of each other. Preparing a scene takes
  up to 6 s there (the projector; the galaxy 3.6 s).

## [0.2.0] - 2026-10-23

Runs on an mFruit OS device without a desktop, and smoothly on a small board.

- **Direct HDMI**: with no desktop session, mDisplay drives the HDMI port itself
  (Linux DRM/KMS) and gives it back to the console on exit; `--output
  auto|desktop|hdmi`. Wide modes are drawn at half size and scaled up once.
- **Missing packages fetched without root**: `install.sh` downloads SDL2,
  NumPy or Pillow (and what they need) from the device's own apt sources into
  the data folder when the system lacks them. This fixes the 0.1.1 install
  failing with exit code 1 on a device without SDL2.
- **New scene: Starlight** — a clear dark sky where stars slowly fade in and
  out, then return elsewhere; nothing moves.
- **Removed: Solar system and Meteor shower.** A saved scene naming one shows
  Galaxy or Starlight instead; their settings (orbits, planet names) are dropped.
- **Motion** setting (Auto, Full, Gentle; Auto is Gentle without a GPU): no
  meteors, the night sky and Minimal hold still, slower turning and twinkling.
- Smooth on the software renderer: a steady frame rate the board keeps up
  with; textures pre-scaled to their drawn size; the galaxy composed at
  whole-degree steps in the background and blended; soft edges drawn 1:1; a
  late frame no longer delays the next one by a whole interval.
- Measured on an Orange Pi Zero 2W (1 GB) on HDMI at 1280×720: Galaxy,
  Starlight and Minimal at a steady 24 fps; Night sky, Nebula, Aurora and the
  projector at a steady 15 fps (frame times within 1 ms of each other).
  The picture on the monitor was not checked by eye.

## [0.1.1] - 2026-10-22

First release with the mFruit OS package attached (`mdisplay-0.1.1.tar.gz`
and `SHA256SUMS`); the app is the same as 0.1.0.

- v0.1.0 was published by hand without the package: the release workflow
  stopped at its checks, because text pasted into `tools/benchmark.py` was
  not Python. The file is code again; `tools/` is not part of the package.
- Not verified on a device (as 0.1.0): physical HDMI, a Whisplay board with
  a desktop on HDMI, keys typed into the window, a live Wayland session.

## [0.1.0] - 2026-10-22

First version (published on GitHub without its package; use 0.1.1).

- Eight ambient scenes on an HDMI screen: Galaxy, Night sky, Nebula, Aurora,
  Solar system, Meteor shower, Galaxy projector, Minimal. Procedural, offline,
  seeded; cross-fades; automatic rotation; sleep timer.
- Galaxy projector: turning nebula clouds and laser stars, drawn larger than
  the screen's diagonal so no edge ever shows; colour themes, laser colours
  and turning speed as settings.
- Soft edges (Off, Soft, Strong): every scene fades to black at the screen's
  border, so the picture floats without a visible rectangle.
- mFruit OS app (`mdisplay`, mFruit OS 1.4.0+, SDK 1.5.0): the Whisplay LCD
  is the remote control — now showing with a thumbnail, a Scenes list to
  choose any scene, Settings; mFruit OS gestures and keyboard through the SDK.
- Desktop window through SDL2 (system libSDL2 2.0.18+, via ctypes): GPU
  renderer when available, SDL's software renderer otherwise; desktop full
  screen on a chosen screen; finds the desktop session itself when started by
  mFruit OS; `--diagnose` and `--list-displays`.
- Settings with validation, atomic saves and recovery from a broken file;
  quality presets Eco, Balanced, High, Ultra (Auto never picks Ultra).
- Tests: unit, offscreen rendering, application, LCD remote, daemon contract,
  and install/launch/exit/uninstall against the real whisplay-daemon code
  with mFruit OS's launcher. Not verified: physical HDMI output, a Whisplay
  board with a desktop on HDMI, a live Wayland session.
