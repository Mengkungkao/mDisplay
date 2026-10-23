#!/usr/bin/env python3
"""Measure frame cost per scene, resolution and quality, without showing anything.

    python3 tools/benchmark.py                              # 1280x720 and 1920x1080, balanced and high
    python3 tools/benchmark.py --sizes 1920x1080 --qualities eco --seconds 6 --json out.json

Each scene runs unpaced in a hidden window (the frame is rendered into an
offscreen target the size of the screen and presented); every 30th frame the
pixels are read back, which waits for the GPU, so GPU work is included in the
averages. Reported per run: frames per second without a cap, frame time
(median, 95th percentile), CPU time per frame and the process's peak memory.

This measures rendering cost on *this* machine. It is not the frame rate on a
visible screen (vsync, compositor and scan-out are not included); use
``run.sh --stats`` on the real screen for that.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def measure(display, scene_id, size, quality_name, seconds, settings_cls, seed=7):
    from app.engine import Engine
    from app.scenes.base import SceneContext, resolve_quality
    canvas = display.canvas
    settings = settings_cls()
    settings.set("transition_seconds", 0)
    quality = resolve_quality(quality_name, display.accelerated)
    canvas.width, canvas.height = size
    target = canvas.target(*size, name="bench")
    engine = Engine(canvas, settings, lambda: SceneContext(size[0], size[1], quality, settings,
                                                           seed=seed,
                                                           accelerated=display.accelerated,
                                                           max_texture=canvas.max_texture),
                    synchronous=True)
    started = time.perf_counter()
    engine.request(scene_id, "benchmark")
    with canvas.into(target):
        engine.draw()
    prepare = time.perf_counter() - started
    engine.fade_start -= 60
    frames, times = 0, []
    cpu0 = time.process_time()
    wall0 = last = time.perf_counter()
    while time.perf_counter() - wall0 < seconds:
        engine.update(1 / 60)
        with canvas.into(target):
            engine.draw(0.85)
            if frames % 30 == 29:
                canvas.read_rgba()                 # wait for the GPU
        canvas.image(target, 0, 0, size[0], size[1])
        canvas.present()
        now = time.perf_counter()
        times.append(now - last)
        last = now
        frames += 1
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    engine.close()
    target.destroy()
    times.sort()
    return {
        "scene": scene_id, "size": f"{size[0]}x{size[1]}", "quality": quality.name,
        "prepare_s": round(prepare, 2), "frames": frames,
        "uncapped_fps": round(frames / wall, 1),
        "frame_ms_p50": round(1000 * times[len(times) // 2], 2),
        "frame_ms_p95": round(1000 * times[int(len(times) * 0.95)], 2),
        "cpu_ms_per_frame": round(1000 * cpu / max(1, frames), 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenes", default="all")
    parser.add_argument("--sizes", default="1280x720,1920x1080")
    parser.add_argument("--qualities", default="balanced,high")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--video-driver", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    from app.config import Settings
    from app.display import session as sessions
    from app.display.desktop import DesktopDisplay
    from app.scenes import catalog
    if args.video_driver:
        os.environ["SDL_VIDEODRIVER"] = args.video_driver
    else:
        found = sessions.find_session()
        if found.chosen is None:
            raise SystemExit(f"benchmark: {found.problem}")
        sessions.apply(found.chosen)
    sizes = [tuple(int(v) for v in s.split("x")) for s in args.sizes.split(",")]
    biggest = max(sizes)
    display = DesktopDisplay(fullscreen=False, window_size=biggest, renderer=args.renderer,
                             hidden=True).open()
    scenes = catalog.SCENE_IDS if args.scenes == "all" else args.scenes.split(",")
    results = []
    try:
        print(f"# {platform.node()} {platform.machine()} {display.driver} "
              f"({'GPU' if display.accelerated else 'software'}) on {display.video_driver}")
        print(f"{'scene':10} {'size':10} {'quality':9} {'prep s':>6} {'fps':>7} {'p50 ms':>7} "
              f"{'p95 ms':>7} {'cpu ms':>7} {'rss MB':>7}")
        for size in sizes:
            for quality in args.qualities.split(","):
                for scene_id in scenes:
                    r = measure(display, scene_id, size, quality, args.seconds, Settings)
                    results.append(r)
                    print(f"{r['scene']:10} {r['size']:10} {r['quality']:9} {r['prepare_s']:6.2f} "
                          f"{r['uncapped_fps']:7.1f} {r['frame_ms_p50']:7.2f} {r['frame_ms_p95']:7.2f} "
                          f"{r['cpu_ms_per_frame']:7.2f} {r['peak_rss_mb']:7.1f}", flush=True)
    finally:
        display.close()
    if args.json:
        with open(args.json, "w") as handle:
            json.dump({"machine": platform.machine(), "node": platform.node(),
                       "renderer": display.driver, "results": results}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())


90