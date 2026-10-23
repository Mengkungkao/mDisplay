# 2026-10-23 — Phase 1: refined scenes on the Orange Pi Zero 2W

- **Revision:** working tree on top of `a5ac8ae` (mDisplay 0.3.0, not yet committed)
- **Device:** OrangePi Zero2 W, 1 GB, Cortex-A53, no GPU renderer; Orange Pi 1.0.2
  Jammy (Ubuntu 22.04), kernel 6.1.31-sun50iw9; Python 3.10.12, SDL 2.0.20,
  NumPy 1.21.5, Pillow 9.0.1
- **Output:** the monitor was **disconnected** during this session
  (`/sys/class/drm/card0-HDMI-A-1/status`: disconnected), so the HDMI path ran
  with a stand-in KMS output: the same drawing at 640×360 and the same scale-up
  into a 1280×720 XRGB buffer, but no page flip and no wait for the vertical blank
- **Settings:** defaults in a temporary data folder (quality Auto → Eco, motion
  Auto → Gentle, brightness 0.85, soft edges), seed 3

## Commands

`fake_hdmi_bench.py` (kept outside the repository) replaced
`Application._open_display` with `_use_kms(<stand-in>, [])`, ignored frame
statistics from the first 10 s and ran each scene for 32 s:

```bash
MDISPLAY_DATA=$(mktemp -d) python3 fake_hdmi_bench.py --standalone --scene <id> \
    --seed 3 --duration 32 --stats <file>
```

`prepare_bench.py` timed `create(ctx).prepare()` for each scene at 640×360,
software, Eco, Gentle.

## Results

| Scene | Prepare | Steady rate | Frame p50 / p95 / max (ms) | Drawing p50 / p95 (ms) | Peak RSS |
|---|---|---|---|---|---|
| Galaxy (inside, new) | 3.43 s | 24 fps | 41.5 / 42.6 / 42.7 | 30.5 / 30.7 | 132 MB |
| Galaxy (outside) | 1.05 s | 24 fps | 41.5 / 42.5 / 42.8 | 32.6 / 32.9 | 68 MB |
| Night sky | 0.57 s | 20 fps | 50.2 / 50.6 / 50.9 | 39.4 / 39.6 | 58 MB |
| Nebula (slower) | 0.61 s | 15 fps | 66.8 / 67.2 / 67.4 | 43.4 / 43.6 | 71 MB |
| Aurora (from below) | 0.27 s | 15 fps | 66.9 / 67.2 / 67.3 | 47.6 / 47.8 | 54 MB |
| Starlight | 0.10 s | 24 fps | 41.5 / 42.5 / 42.7 | 22.0 / 22.2 | 58 MB |
| Galaxy projector (refined) | 1.38 s | 20 fps | 49.8 / 50.9 / 51.1 | 40.9 / 41.1 | 69 MB |
| Minimal | 0.04 s | 24 fps | 42.0 / 42.3 / 42.5 | 17.4 / 17.6 | 50 MB |

The aurora from below first drew its rays as triangle meshes, as on a GPU:
106 ms a frame (8 fps). Measured on the board, the cost was SDL's software
rasteriser (about 40 ms for the meshes, which pays per triangle and for each
long diagonal triangle's bounding box) and NumPy noise per call (about 27 ms).
Drawing the curtains into a half-size layer, untextured rays or shorter
segments each gained little (99, 108, 78 ms). The software path now paints the
curtains with NumPy in polar coordinates around the zenith into a 230×129 image
(24 ms) with one noise evaluation per curtain per frame: 48 ms, 15 fps, the
same as 0.2's aurora.

## Quality first (the owner's priority, same day)

After the owner asked for quality before speed: Quality Auto became Balanced on
the software renderer too, the scenes' textures are made at the size they are
drawn (no scale-up), the aurora is painted at 0.5 instead of 0.36 of the
screen, and a tile seam was fixed. Same board, same stand-in output, Balanced:

| Scene | Prepare | Steady rate | Frame p50 / p95 / max (ms) | Drawing p50 / p95 (ms) | Peak RSS |
|---|---|---|---|---|---|
| Galaxy (inside) | 3.58 s | 24 fps | 41.3 / 42.5 / 43.4 | 34.6 / 34.8 | 132 MB |
| Galaxy (outside) | 4.61 s | 20 fps | 50.2 / 50.5 / 50.8 | 36.3 / 36.7 | 102 MB |
| Night sky | 2.13 s | 15 fps | 66.6 / 67.6 / 67.7 | 45.1 / 45.4 | 67 MB |
| Nebula | 3.32 s | 15 fps | 66.4 / 67.4 / 67.7 | 54.3 / 54.6 | 89 MB |
| Aurora | 0.31 s | 12 fps | 83.4 / 83.8 / 84.3 | 65.1 / 65.4 | 57 MB |
| Starlight | 0.10 s | 24 fps | 41.9 / 42.2 / 42.5 | 25.8 / 26.1 | 58 MB |
| Galaxy projector | 6.24 s | 15 fps | 66.5 / 67.5 / 67.7 | 52.3 / 53.0 | 128 MB |
| Minimal | 0.04 s | 24 fps | 41.6 / 42.6 / 42.8 | 17.9 / 18.1 | 50 MB |

(The projector's first measurement, before its clouds' wisps were made at a
third of the size instead of a half, took 9.39 s to prepare.)

## Not verified

- **On a real HDMI screen.** 0.2.0 on real HDMI showed one frame in seven about
  10 ms slower than the rest in the 15 fps scenes; the stand-in has no page flip,
  so on the screen the Night sky and the projector may settle at 15 fps instead
  of 20. Re-measure with `--output hdmi` when the monitor is connected.
- The look of the new scenes on the monitor by eye; they were reviewed only in
  offscreen previews (software renderer at 640×360, OpenGL at 1280×720).
- Launching 0.3.0 from mFruit OS Home on the board.

## Discovered

- The inside galaxy's preparation takes 3.4 s on the board and peaks at
  132 MB; it is the default scene, so mDisplay's first picture appears about
  4 s after launch (the LCD remote shows *loading* meanwhile).
