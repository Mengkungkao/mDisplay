#!/usr/bin/env python3
"""Long-running check: cycle every scene for a while and watch memory and textures.

    python3 tools/soak.py --minutes 10 --every 30 --json /tmp/soak.json

Runs the real engine with cross-fades in a hidden window (nothing on screen) at
about 30 frames a second, changing scene every ``--every`` seconds, and samples
the process's resident memory, the number of live textures and frame times.
A leak shows as memory or textures that keep growing from one round of scenes
to the next.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def rss_mb() -> float:
    with open("/proc/self/statm") as handle:
        pages = int(handle.read().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE") / 1e6


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--every", type=float, default=30.0)
    parser.add_argument("--size", default="1920x1080")
    parser.add_argument("--quality", default="auto")
    parser.add_argument("--video-driver", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    from app.config import Settings
    from app.display import session as sessions
    from app.display.desktop import DesktopDisplay
    from app.engine import Engine
    from app.scenes import catalog
    from app.scenes.base import SceneContext, resolve_quality
    from app.timing import FramePacer
    if args.video_driver:
        os.environ["SDL_VIDEODRIVER"] = args.video_driver
    else:
        found = sessions.find_session()
        if found.chosen is None:
            raise SystemExit(f"soak: {found.problem}")
        sessions.apply(found.chosen)
    w, h = (int(v) for v in args.size.split("x"))
    display = DesktopDisplay(fullscreen=False, window_size=(w, h), hidden=True).open()
    canvas = display.canvas
    canvas.width, canvas.height = w, h
    settings = Settings()
    settings.set("transition_seconds", 3.0)
    quality = resolve_quality(args.quality, display.accelerated)
    target = canvas.target(w, h, "soak")
    engine = Engine(canvas, settings, lambda: SceneContext(w, h, quality, settings, seed=11,
                                                           accelerated=display.accelerated,
                                                           max_texture=canvas.max_texture))
    pacer = FramePacer(30)
    samples, frame_times = [], []
    started = last = time.monotonic()
    next_change = started
    index = 0
    end = started + args.minutes * 60
    try:
        while time.monotonic() < end:
            now = time.monotonic()
            if now >= next_change:
                scene_id = catalog.SCENE_IDS[index % len(catalog.SCENE_IDS)]
                engine.request(scene_id, "soak")
                index += 1
                next_change = now + args.every
                samples.append({"t": round(now - started, 1), "scene": scene_id,
                                "rss_mb": round(rss_mb(), 1), "textures": canvas.live_textures,
                                "round": (index - 1) // len(catalog.SCENE_IDS)})
                print(json.dumps(samples[-1]), flush=True)
            engine.update((now - last) * float(settings["speed"]))
            frame_times.append(now - last)
            last = now
            with canvas.into(target):
                engine.draw(0.85)
            canvas.image(target, 0, 0, w, h)
            canvas.present()
            pacer.frame_done()
            time.sleep(pacer.remaining())
    finally:
        engine.close()
        display.close()
    rounds = {}
    for sample in samples:
        rounds.setdefault(sample["round"], []).append(sample)
    summary = {
        "minutes": args.minutes, "size": args.size, "quality": quality.name,
        "renderer": display.driver, "frames": len(frame_times),
        "frame_ms_max": round(1000 * max(frame_times[10:] or [0]), 1),
        "rss_mb_per_round": {r: max(s["rss_mb"] for s in v) for r, v in rounds.items()},
        "textures_per_round": {r: max(s["textures"] for s in v) for r, v in rounds.items()},
        "samples": samples,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, indent=2))
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(summary, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
