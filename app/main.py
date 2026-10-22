"""mDisplay: animated galaxies, night skies, nebulae and auroras on an HDMI screen.

    python3 -m app.main                  run (full screen on the saved screen)
    python3 -m app.main --windowed       in a window
    python3 -m app.main --diagnose       what the desktop and graphics offer, and what is missing
    python3 -m app.main --list-displays  the screens SDL sees

Started by mFruit OS (``run.sh`` through mfruit-run), mDisplay also shows a
remote control on the Whisplay LCD; run by hand on a desktop it is just the
window. Run ``--help`` for every option.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_size(text: str) -> tuple:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, e.g. 1280x720") from exc
    if not (160 <= w <= 16384 and 90 <= h <= 16384):
        raise argparse.ArgumentTypeError("size out of range")
    return w, h


def build_parser() -> argparse.ArgumentParser:
    from .config import QUALITIES
    from .scenes.catalog import SCENE_IDS
    parser = argparse.ArgumentParser(prog="mdisplay", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"mDisplay {__version__}")
    parser.add_argument("--diagnose", action="store_true",
                        help="report the graphics environment and exit")
    parser.add_argument("--json", action="store_true", help="with --diagnose: JSON output")
    parser.add_argument("--list-displays", action="store_true", help="list screens and exit")
    parser.add_argument("--scene", choices=SCENE_IDS, help="start with this scene (not saved)")
    parser.add_argument("--quality", choices=QUALITIES, help="quality preset (not saved)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fullscreen", dest="fullscreen", action="store_true", default=None,
                      help="full screen (not saved)")
    mode.add_argument("--windowed", dest="fullscreen", action="store_false",
                      help="in a window (not saved)")
    parser.add_argument("--display", default="",
                        help="screen: an output name (DP-0, HDMI-1), display-N or N (not saved)")
    parser.add_argument("--size", type=parse_size, help="window size, e.g. 1280x720")
    parser.add_argument("--renderer", default="auto",
                        help="auto (GPU, else software), opengl, opengles2 or software")
    parser.add_argument("--session", default=os.environ.get("MDISPLAY_SESSION", ""),
                        help="desktop session to use: an X display (:0) or a Wayland socket")
    parser.add_argument("--video-driver", default=os.environ.get("MDISPLAY_VIDEO_DRIVER", ""),
                        help="SDL video driver, bypassing session discovery (tests: dummy; "
                             "also MDISPLAY_VIDEO_DRIVER)")
    parser.add_argument("--output", choices=("auto", "desktop", "hdmi"),
                        default=os.environ.get("MDISPLAY_OUTPUT", "auto"),
                        help="auto: the desktop session, else straight to HDMI when there is no "
                             "desktop; desktop; hdmi (DRM/KMS, no desktop needed)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="close after this many seconds (testing)")
    parser.add_argument("--screenshot", default="",
                        help="with --duration: save the last frame as a PNG")
    parser.add_argument("--stats", default="", help="write frame statistics (JSON) at exit")
    parser.add_argument("--show-info", action="store_true", help="show the frame-rate line")
    parser.add_argument("--seed", type=int, default=0, help="random seed (0 = new each run)")
    parser.add_argument("--standalone", action="store_true",
                        help="never use the Whisplay LCD, even under mFruit OS")
    parser.add_argument("--lcd", action="store_true",
                        help="also show the remote on the Whisplay LCD when run by hand")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    if args.screenshot and not args.duration:
        print("mdisplay: --screenshot needs --duration", file=sys.stderr)
        return 2
    if args.diagnose or args.list_displays:
        from . import diagnostics
        return diagnostics.main(args)
    from .application import Application, Options
    options = Options(scene=args.scene or "", quality=args.quality or "",
                      fullscreen=args.fullscreen, display=args.display, size=args.size,
                      renderer=args.renderer, session=args.session, duration=args.duration,
                      show_info=args.show_info, seed=args.seed, standalone=args.standalone,
                      lcd=args.lcd, screenshot=args.screenshot, stats=args.stats,
                      video_driver=args.video_driver, output=args.output)
    return Application(options).run()


if __name__ == "__main__":
    sys.exit(main())
