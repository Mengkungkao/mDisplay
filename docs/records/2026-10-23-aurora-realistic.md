# 2026-10-23 — Realistic aurora (0.4.0) on the Orange Pi Zero 2W

- **Revision:** working tree on top of `7634425` (mDisplay 0.4.0, not yet committed)
- **Device:** OrangePi Zero2 W, 1 GB, Cortex-A53, no GPU renderer; Orange Pi 1.0.2
  Jammy (Ubuntu 22.04), kernel 6.1.31-sun50iw9; Python 3.10.12, SDL 2.0.20,
  NumPy 1.21.5, Pillow 9.0.1
- **Output:** the monitor was disconnected (`/sys/class/drm/card0-HDMI-A-1/status`),
  so the HDMI path ran with the stand-in KMS output used in
  [the Phase 1 record](2026-10-23-phase1-scenes.md): same drawing at 640×360 and
  scale-up into 1280×720, no page flip
- **Settings:** defaults (quality Auto → Balanced, motion Auto → Gentle), seed 3
- **Reference:** the owner's two photographs of a pink, green and violet aurora
  over a lake, sent on 2026-10-23 (not stored in the repository)

## Results

| Measurement | Result |
|---|---|
| `AuroraSky` set-up at 640×360 | 1.24 s |
| One picture (`render`), six in a row | 0.42 s each |
| Steady rate, 40 s run (first 10 s ignored) | 24 fps (the scene's cap is the quality's 60, the steady rate's list tops at 30) |
| Frame p50 / p95 / max | 41.7 / 42.5 / 43.3 ms |
| Drawing p50 / p95 | 30.8 / 33.1 ms |
| CPU | 108% of one core (the worker making pictures, plus drawing) |
| Peak RSS | 83 MB |

In Gentle motion a new picture is needed every 2.25 s of real time (0.9 s of
aurora time at 40% speed) and one takes 0.42 s, so the worker keeps well ahead.
The 0.3.0 aurora (triangle meshes, then NumPy painting at half area) ran at
12 fps on the same board.

## Not verified

- The look and the rate on a real HDMI screen; the comparison with the
  photographs was made on offscreen renders (software renderer, 640×360,
  960×640 and 1280×720).
- 0.4.0 launched from mFruit OS Home on the board.
