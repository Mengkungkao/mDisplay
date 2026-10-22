#!/usr/bin/env python3
"""Render scenes to PNG files, offscreen and deterministically.

    python3 tools/preview.py --scene galaxy --size 1280x720 --seconds 20 --out /tmp/previews
    python3 tools/preview.py --scene all --renderer software --video-driver dummy --out /tmp/p

Time is simulated (fixed steps), so the same seed and seconds always give the
same image, and nothing waits in real time. The frame is drawn into an
offscreen render target of a hidden window: nothing appears on the screen.
With the GPU renderer this needs a desktop session (it finds one the way the
app does); ``--video-driver dummy --renderer software`` works anywhere.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.config import Settings  # noqa: E402
from app.scenes import catalog  # noqa: E402
from app.scenes.base import SceneContext, resolve_quality  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def render(scene_ids, size, seconds, out_dir, renderer="auto", video_driver="", quality="auto",
           seed=7, settings=None, step=1 / 30.0, verbose=True) -> list:
    from app.display import session as sessions
    from app.display.desktop import DesktopDisplay
    from app.engine import Engine
    from PIL import Image
    if video_driver:
        os.environ["SDL_VIDEODRIVER"] = video_driver
    else:
        found = sessions.find_session()
        if found.chosen is None:
            raise SystemExit(f"preview: {found.problem} (use --video-driver dummy --renderer software)")
        sessions.apply(found.chosen)
    display = DesktopDisplay(fullscreen=False, window_size=size, renderer=renderer, hidden=True).open()
    canvas = display.canvas
    settings = settings or Settings()
    q = resolve_quality(quality, display.accelerated)
    written = []
    os.makedirs(out_dir, exist_ok=True)
    try:
        target = canvas.target(*size, name="preview")
        for scene_id in scene_ids:
            clock = FakeClock()
            settings.set("transition_seconds", 0)
            context = lambda: SceneContext(size[0], size[1], q, settings, seed=seed,  # noqa: E731
                                           accelerated=display.accelerated,
                                           max_texture=canvas.max_texture)
            canvas.width, canvas.height = size
            engine = Engine(canvas, settings, context, now=clock, synchronous=True)
            started = time.perf_counter()
            engine.request(scene_id, "preview")
            prepare = time.perf_counter() - started
            with canvas.into(target):
                engine.draw(float(settings["brightness"]))      # adopt the scene
            steps = int(seconds / step)
            for _ in range(steps):
                clock.t += step
                engine.update(step * float(settings["speed"]))
            clock.t += 10.0                                      # past any fade-in
            with canvas.into(target):
                engine.draw(float(settings["brightness"]))
                pixels = canvas.read_rgba()
            engine.close()
            path = os.path.join(out_dir, f"{scene_id}.png")
            Image.fromarray(pixels[..., :3]).save(path)
            written.append(path)
            if verbose:
                print(f"{scene_id}: {path} ({display.driver}, {q.name}, prepare {prepare:.2f} s)")
    finally:
        display.close()
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scene", default="all", help="a scene id or 'all'")
    parser.add_argument("--size", default="1280x720")
    parser.add_argument("--seconds", type=float, default=12.0, help="simulated time")
    parser.add_argument("--out", required=True)
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--video-driver", default="")
    parser.add_argument("--quality", default="auto")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="a setting for the preview (JSON value), e.g. --set brightness=1.0")
    args = parser.parse_args(argv)
    import json
    w, h = (int(v) for v in args.size.lower().split("x"))
    settings = Settings()
    for item in args.set:
        key, _, value = item.partition("=")
        settings.set(key, json.loads(value))
    ids = catalog.SCENE_IDS if args.scene == "all" else tuple(args.scene.split(","))
    render(ids, (w, h), args.seconds, args.out, args.renderer, args.video_driver, args.quality,
           args.seed, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
