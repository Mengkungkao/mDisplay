# Changelog

Versions follow the manifest. Each section becomes the GitHub release notes.

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
