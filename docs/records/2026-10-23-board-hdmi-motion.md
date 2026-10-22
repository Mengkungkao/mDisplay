# 2026-10-23 — Direct HDMI and gentle motion on an Orange Pi Zero 2W

- **Revision:** working tree on top of `4493ae3` (mDisplay 0.2.0, not yet committed)
- **Device:** OrangePi Zero2 W, 1 GB, Cortex-A53, no GPU renderer; Orange Pi 1.0.2
  Jammy (Ubuntu 22.04), kernel 6.1.31-sun50iw9; mFruit OS 1.6.2 installed
- **Software:** Python 3.10.12, SDL 2.0.20, NumPy 1.21.5, Pillow 9.0.1 (system packages)
- **Output:** no desktop session; mDisplay on HDMI-A-1 through DRM/KMS at
  1280×720 @ 60 Hz, drawn at 640×360 by SDL's software renderer and scaled up
- **Settings:** defaults in a temporary data folder (quality Auto → Eco,
  motion Auto → Gentle, brightness 0.85, soft edges), seed 3

## Commands

The development copy was synced to `~/mdisplay-dev` and run standalone (no
mFruit OS focus) for each scene, 32 s, discarding the first 10 s (start-up and
the frame-rate choice):

```bash
MDISPLAY_DATA=$(mktemp -d) python3 bench.py --output hdmi --standalone \
    --scene <id> --seed 3 --duration 32 --stats <file>
```

`bench.py` wrapped `app.main` and ignored frame statistics from the first 10 s.

## Results (steady state)

| Scene | Steady rate | Frame p50 / p95 / max (ms) | Drawing p50 / p95 (ms) | CPU (one core) | RSS |
|---|---|---|---|---|---|
| Galaxy | 24 fps | 41.6 / 42.5 / 44.7 | 32.8 / 33.2 | 93% | 65 MB |
| Night sky | 15 fps | 66.5 / 67.6 / 68.4 | 39.6 / 49.8 | 73% | 55 MB |
| Nebula | 15 fps | 66.7 / 67.2 / 67.7 | 44.2 / 49.8 | 80% | 68 MB |
| Aurora | 15 fps | 66.7 / 67.0 / 67.7 | 45.3 / 49.8 | 81% | 60 MB |
| Starlight | 24 fps (its cap) | 41.7 / 42.6 / 42.7 | 22.3 / 22.5 | 59% | 55 MB |
| Galaxy projector | 15 fps | 66.6 / 67.7 / 68.0 | 38.8 / 49.8 | 72% | 61 MB |
| Minimal | 24 fps (its cap) | 41.4 / 42.5 / 42.7 | 17.6 / 17.9 | 48% | 47 MB |

Every scene now runs at an even rhythm: the 95th-percentile frame time is
within about 1 ms of the median. Before this work (same board, 0.1.1 drawing
code at half size, scaled-up render target) the scenes ran at 7–26 fps with
uneven frames; the galaxy re-composed its tilted image every 1.25 s (a 113 ms
frame), now never on the render thread.

What made the difference, measured on the board:

| Change | Cost per frame before → after |
|---|---|
| Scale-up into the frame buffer: render-target `RenderCopy` + read-back → read-back + `SDL_SoftStretchLinear` | 25 ms → 10 ms |
| Soft edges: four scaled multiply strips → 1:1 strips | 5.1 ms → 1.8 ms |
| Galaxy composite: SDL turn + tilt on the render thread → Pillow on the worker, blended | 113 ms frame every 1.25 s → none |

## Not verified

- The picture on the monitor was **not looked at**: page flips completed and
  timings were measured, but nobody watched the screen during these runs.
- Launching 0.2.0 from mFruit OS Home on this board (the runs were standalone);
  `install.sh` fetching packages on the board (the board already had them; the
  fetch was tested with stand-in tools and in an Ubuntu 22.04 root).

## Discovered

- In the 15 fps scenes about one frame in seven takes ~10 ms longer
  (bimodal: ~40 ms and ~50 ms) with no scene work to explain it; it does not
  show in the frame rhythm (66.7 ms budget) but keeps those scenes from
  20 fps. Not investigated further.
- Hardware scaling on a DRM plane would save the remaining ~10 ms stretch
  (follow-up in docs/DISPLAY_BACKENDS.md).
