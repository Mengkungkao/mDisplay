# Testing

```bash
bash tools/check.sh              # everything CI runs (MFRUIT_OS=~/MFruitOS for the mFruit OS parts)
bash tools/check.sh --quick      # without the test suite
python3 -m pytest -q tests       # the suite (also: python3 -m unittest discover -s tests)
bash test.sh                     # the smoke test mFruit OS runs before activating a version
```

No test opens a window on a real screen: `tests/helpers.py` forces SDL's
dummy video driver and removes `DISPLAY`/`WAYLAND_DISPLAY`. The mFruit OS
integration tests run the real whisplay-daemon code, so **never run two
real-daemon suites at once** (mFruit OS's and this one share fake-app
clean-up).

## Levels

| Level | What | Where |
|---|---|---|
| Unit | settings, timing, meteors, planet positions, session discovery, key names, menus | `test_config.py`, `test_timing.py`, `test_meteors.py`, `test_astro.py`, `test_session.py` |
| Rendering (offscreen, software renderer) | every scene at three sizes and shapes; animates; holds still when paused; same seed same picture; 24 vs 60 fps same picture; round Sun at every aspect ratio; settings change the picture; resizing; soft edges black at the border; projector options and corner coverage; no texture left behind | `test_scenes.py`, `test_engine.py` |
| Application (SDL dummy driver) | window keys, panel, every menu row changes something, reset needs two presses, saved settings (command-line choices not saved), corrupt file, focus, minimise, idle when paused, sleep timer actions, resize; as a process: run + screenshot + stats, SIGTERM exit 0 within 3 s, actionable errors | `test_application.py` |
| LCD remote (SDK `InputController`, unthreaded, fake clock) | every gesture on every screen; each scene chosen from the Scenes list; nothing acts or draws without the LCD; keys pressed elsewhere ignored; every screen inside mFruit OS's chrome; LCD menu = HDMI panel rows | `test_remote.py` |
| Daemon contract (scripted daemon) | Esc claimed before the screen; first frame; focus revoked/regained with a new framebuffer; exit request; focus released | `test_whisplay_lifecycle.py` |
| mFruit OS integration (REAL whisplay-daemon + REAL launcher, simulated board) | sideload with hooks, Home entry, launch through ApplicationManager, Scenes list and Settings by button gestures, exit by 4×, relaunch keeps settings, daemon exit request, force stop, uninstall | `test_mfruitos_integration.py` (needs `MFRUIT_OS`) |
| Package | manifest per the app contract, hooks, smoke test, SDK and contract copies, `check-app.py`, release archive | `test_package.py` |
| Live desktop | the window and full screen on a real monitor, real keys, measured frame times | by hand, recorded in `docs/records/` |
| Device | a Whisplay board with a desktop on HDMI | NOT VERIFIED (see the README's status table) |

## Measuring

```bash
python3 tools/benchmark.py                       # cost per frame, every scene, 720p/1080p, hidden window
python3 tools/soak.py --minutes 10 --json s.json # memory and textures over many scene changes
./run.sh --stats stats.json --duration 30        # the real screen: fps, frame times, CPU, memory
python3 tools/preview.py --scene all --out /tmp/p   # PNGs, offscreen and deterministic
```

Write results into a dated record (`docs/records/YYYY-MM-DD-*.md`) with the
machine, OS, renderer, resolution, commands and what was not covered. A
benchmark in a hidden window measures rendering cost, not what reaches a
screen; a screenshot shows composition, not animation.

## Live checklist (a real screen)

1. `./run.sh --diagnose`: no problems; note the screen and renderer.
2. `./run.sh --windowed --show-info`: the window appears; stars twinkle; `→`
   changes scene with a cross-fade; `Space` pauses (frame line stops), again
   resumes; `B` opens the panel, `←/→` change a value visibly, `Esc` closes it.
3. `F11`: full screen on the chosen screen, no border, no pointer; `F11` back.
4. Resize the window: the scene fills it, circles stay round.
5. Leave it 30 minutes: smooth, no growth in memory (`--stats`).
6. `Esc`: closes; the terminal shows exit status 0.

On an mFruit OS board with a desktop on HDMI, additionally: launch from
Home; the LCD shows the remote within a second; button and keyboard each
choose a scene from the Scenes list; 4× from the remote returns to Home and
the HDMI window closes; Settings → Sleep timer → Close mDisplay returns to
Home when it ends.
