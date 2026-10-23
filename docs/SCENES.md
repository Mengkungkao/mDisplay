# Adding a scene

A scene is one module in `app/scenes/` and one line in
`app/scenes/catalog.py`. Nothing else changes: the engine, the HDMI panel, the
LCD Scenes list, settings validation and the smoke test pick it up from the
catalogue.

## 1. Write the class

```python
# app/scenes/comet.py
"""Scene — Comet: a comet crossing a starry sky."""

from __future__ import annotations

from ..gfx.canvas import ADD
from .base import Scene
from .parts import StarField, common_sprites, density_count


class CometScene(Scene):
    id = "comet"
    STARS = 900

    def prepare(self) -> None:                     # worker thread: NumPy/Pillow only
        rng = self.ctx.rng("comet")                 # seeded: same seed, same picture
        capacity, _ = density_count(self.STARS, self.ctx.quality, 2.0)
        self.stars = StarField(rng, capacity)
        self.sprites = common_sprites(self.ctx.quality)

    def setup(self, canvas) -> None:               # render thread: upload textures
        self.star = self.upload(canvas, self.sprites["star"], ADD, "star")
        self.sprites = None                         # free the CPU copies

    def update(self, dt: float, t: float) -> None:  # dt in scene seconds (0 while paused)
        self.t = t

    def draw(self, canvas) -> None:
        canvas.clear((2, 3, 8))
        _, count = density_count(self.STARS, self.ctx.quality,
                                 float(self.setting("star_density", 1.0)))
        self.stars.draw(canvas, self.star, self.t, self.width, self.height, count=count)
```

Then add it to `SCENES` in `app/scenes/catalog.py`:

```python
SceneInfo("comet", "Comet", "A comet crossing a starry sky", "app.scenes.comet:CometScene"),
```

The id is permanent once released: it is stored in users' settings.

## 2. Rules

- **Draw only through the canvas** (`app/gfx/canvas.py`): `clear`, `image`,
  `centered`, `tiled`, `fill`, `geometry`, `QuadBatch`/`Mesh` from
  `app/gfx/batch.py`. Never import SDL, the window or the input.
- **Time, not frames.** Move things by `t` (scene seconds) or `dt`. The tests
  render a scene at 24 and 60 fps and expect the same picture unless it has
  random events.
- **Resolution independence.** Size things from `self.unit` (1.0 at 1080
  pixels on the short side) and positions from `self.width`/`self.height`.
  Keep circles round: scale both axes by the same factor. Test portrait too.
- **Seeded randomness**: `self.ctx.rng("name")` only.
- **Nothing heavy in `draw`**: no allocation of big arrays, no per-pixel Python
  loops; generate textures in `prepare` (`gfx/noise.py`, `gfx/sprites.py`).
- **Quality**: scale counts by `self.ctx.quality.stars`, texture sizes with
  `self.ctx.texture_size(base)`, extra layers by `quality.detail`.
- **Settings**: read with `self.setting(key, default)` every frame, or return
  True from `settings_changed(keys)` to be rebuilt (e.g. a new texture).
  A new setting is added to `app/config.py` (`SCHEMA`) and, if users should
  see it, to `MENU_SETTINGS` in `app/controls.py`, plus docs/CONFIGURATION.md.
- **Calm**: dark overall, no flashes, colour changes over minutes. The tests
  fail a scene whose average is too bright for an ambient screen.
- **Release** everything: textures made with `self.upload` are destroyed by
  `close()`. Render targets made directly must be appended to `self.textures`.
- **Long preparations** call `self.checkpoint()` between their expensive steps:
  it stops the preparation (raises `Cancelled`) once the scene is no longer
  wanted, for example when the app is closing, so a quit never waits for it.
- **Variants**: a scene with views chosen by a setting overrides the class
  method `create(ctx)` to return the view's class (see `galaxy.py`), and returns
  True from `settings_changed` for that setting.
- **The software renderer** (a board without a GPU) pays per pixel and per
  triangle: draw textures 1:1 (`self.fit`), avoid turning big images, and keep
  long thin triangles few. When per-frame geometry is too heavy, painting a
  small image with NumPy and scaling it up can be cheaper (`aurora.py`).
  Measure on the board (docs/TESTING.md).
- **Edges**: fill the whole screen. If something turns, make it larger than
  the screen's diagonal (see `projector.py`), so no edge ever comes into view.

## 3. Check it

```bash
python3 tools/preview.py --scene comet --size 1280x720 --seconds 30 --out /tmp/p   # PNG, offscreen
python3 -m pytest tests/test_scenes.py tests/test_engine.py                        # all scenes, every size
./run.sh --windowed --scene comet --show-info                                        # live, with frame times
python3 tools/benchmark.py --scenes comet                                            # cost per frame
```
