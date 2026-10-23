# Configuration

mDisplay has one settings file, written by the app; users change it from the
HDMI panel or the LCD remote. The schema and its validation are
`app/config.py` (`SCHEMA`); this page describes it.

## Where

| Run by | File |
|---|---|
| mFruit OS | `$WHISPLAY_OS_APP_DATA/settings.json` (`~/.whisplay-os/apps/mdisplay/data/`; kept across updates, snapshotted before each update, kept by *Uninstall*, removed by *Delete data*) |
| hand, on a desktop | `$XDG_CONFIG_HOME/mdisplay/settings.json` (`~/.config/mdisplay/`) |
| tests, a second profile | `$MDISPLAY_DATA/settings.json` |

`install.sh` may add a `sysroot/` beside it (system packages it had to fetch
without root: SDL2, NumPy, Pillow and what they need; see
[Install](../README.md#install)) and a `venv/` (only when NumPy had to come from
pip). Nothing else is written; no system file is touched.

## Format

UTF-8 JSON, one object, at most 256 KiB:

```json
{"schema": 1, "scene": "projector", "speed": 1.0, "edge_fade": "soft", "fullscreen": true}
```

Missing keys take their defaults. Values are validated one by one: a wrong
type or an unknown choice falls back to that key's default; a number out of
range is clamped; either way the problem is logged and shown briefly on the
screen. `orbits` and `planet_labels`, the settings of the solar system scene
removed in 0.2.0, are dropped quietly when the file is read. Keys this version does not know (from a newer mDisplay) are kept and
written back unchanged. `schema` is 1; a larger value is accepted with a
notice (newer keys are kept, not interpreted).

A file that is not valid JSON (for example cut short by a power loss) is
renamed `settings.json.corrupt-YYYYMMDD-HHMMSS`, kept as evidence, and the
defaults are used. Saving writes a temporary file in the same folder, syncs it
and renames it over `settings.json`, so the file is always either the old or
the new version. Changes are saved 1.5 s after the last one and at exit; a
failed save is reported and retried 30 s later.

Command-line choices (`--scene`, `--quality`, `--windowed`/`--fullscreen`,
`--display`) apply to that run only and are not saved.

## Keys

| Key | Kind | Default | Range | Values (as shown, stored) |
|---|---|---|---|---|
| `scene` | choice | `"galaxy"` | | Galaxy `galaxy`, Night sky `nightsky`, Nebula `nebula`, Aurora `aurora`, Starlight `starlight`, Galaxy projector `projector`, Minimal `minimal`. A saved scene that was removed in 0.2.0 shows its replacement: `solar` → `galaxy`, `meteors` → `starlight` |
| `auto_rotate` | flag | `false` | | change scenes automatically, in catalogue order |
| `rotate_minutes` | choice | `10` | | 1, 2, 5, 10, 15, 30, 60, 120 minutes |
| `transition_seconds` | number | `3.0` | 0–10 | cross-fade length; 0 = cut |
| `speed` | number | `1.0` | 0.25–3 | animation speed (steps 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3) |
| `brightness` | number | `0.85` | 0.2–1 | overall brightness of the scene (the panel stays readable) |
| `motion` | choice | `"auto"` | | `auto` (Gentle without a GPU, Full with one), `full`, `gentle` (nothing travels across the sky: no meteors, the night sky and Minimal hold still; slower turning and drifting elsewhere; calmer twinkling: smooth at the few frames a second of a small board) |
| `edge_fade` | choice | `"soft"` | | Soft edges: `off`, `soft` (a fade at the border), `strong` (wider, with a projector-like fall-off): the screen's edge does not show |
| `star_density` | number | `1.0` | 0.25–2 | multiplies star counts |
| `nebula_intensity` | number | `1.0` | 0–1.5 | gas and glow layers: nebula, galaxy arms, Milky Way, projector clouds |
| `meteor_frequency` | number | `1.0` | 0–3 | multiplies each scene's meteor rate; 0 = none |
| `galaxy_view` | choice | `"inside"` | | Galaxy view: `inside` (the Milky Way across the sky, seen from within the disk), `outside` (a spiral galaxy turning, seen at an angle; the view before 0.3.0) |
| `projector_colors` | choice | `"cosmic"` | | Galaxy projector colours: `cosmic`, `ocean`, `aurora`, `sunset`, `rainbow` |
| `projector_lasers` | choice | `"green"` | | `green`, `red`, `both`, `off` |
| `projector_rotation` | choice | `"slow"` | | `off`, `slow` (a turn in 8 min), `medium` (3 min), `fast` (75 s), at speed 1 |
| `quality` | choice | `"auto"` | | `auto` (Balanced, with or without a GPU: quality before frame rate; never Ultra), `eco`, `balanced`, `high`, `ultra` |
| `fullscreen` | flag | `true` | | desktop full screen on the chosen screen (no mode change) |
| `display` | text | `"auto"` | 1–64 of `A-Za-z0-9 _.:#()+-` | `auto` = the first screen; else a screen's key from `--list-displays` (X11 output name such as `HDMI-1`, or `display-N`). A missing screen is never replaced silently: a notice says where the picture went |
| `sleep_minutes` | choice | `0` | | 0 (off), 15, 30, 45, 60, 90, 120, 180, 240 |
| `sleep_action` | choice | `"minimal"` | | `minimal` (switch to the Minimal scene), `pause`, `exit` (close; under mFruit OS back to Home) |
| `unfocused` | choice | `"reduce"` | | desktop only, when the window loses focus: `keep`, `reduce` (20 fps), `pause` |
| `show_scene_name` | flag | `true` | | show a scene's name for a few seconds when it starts |
| `clouds` | flag | `true` | | night sky clouds |
| `horizon` | flag | `true` | | night sky tree line |
| `mountains` | flag | `true` | | aurora: a thin horizon of hills and trees at the bottom edge |
| `allow_screen_blanking` | flag | `false` | | let the desktop blank the screen while scenes run (it may always while paused) |
| `vsync` | choice | `"auto"` | | `auto` (on when the screen's refresh rate matches the frame-rate cap), `on`, `off`; not in the menus |

## Quality presets

| Preset | Frame-rate cap | Stars | Textures | Extras |
|---|---|---|---|---|
| Eco | 30 | 0.4× | 0.5× | fewest layers; no grain |
| Balanced | 60 | 1× | 0.75× | grain on GPU renderers |
| High | 60 | 1.6× | 1× | more layers and octaves |
| Ultra | the screen's refresh (≤144) | 2.4× | 1.25× | most detail |

Calm scenes cap lower (Minimal: 24 fps).
