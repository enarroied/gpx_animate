# gpx-animate

[![ci](https://github.com/enarroied/gpx_animate/actions/workflows/ci.yml/badge.svg)](https://github.com/enarroied/gpx_animate/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/enarroied/gpx_animate/branch/master/graph/badge.svg)](https://codecov.io/gh/enarroied/gpx_animate)

Turn a GPX file into a short animated MP4 for travel content (YouTube, Medium, Shorts, Reels).

The animation draws the track progressively from start to finish, then holds the
completed trace for a moment so it lingers on screen.

Built for reproducibility: everything brandable is config-driven, and the whole
pipeline runs from a single command.

---

## 1. Purpose

- **Input:** one `.gpx` file (tracks, or routes as a fallback).
- **Output:** one `.mp4` file, ready to upload.
- **Use case:** short "trip reveal" clips for travel videos and blog posts.
- **Target user:** a solo creator who wants a repeatable, scriptable workflow —
  not a one-off GUI session.

---

## 2. Pipeline

```
GPX file
  │
  ├─ parse (gpxpy)               → lons, lats, elevations, trip name
  ├─ geometry (numpy)            → cumulative distance (haversine), elevation gain
  ├─ project (pyproj)            → EPSG:4326 → EPSG:3857 (Web Mercator)
  ├─ basemap (contextily)        → tiles under the track
  ├─ render (matplotlib)         → one PNG per frame
  │     · faint full track
  │     · bright growing line (LineCollection, updated per frame)
  │     · moving position marker
  │     · live HUD (distance, elevation)
  │     · trip title
  │     · optional logo
  └─ encode (ffmpeg)             → H.264 MP4, yuv420p, CRF 18
```

Frames are written to a temp directory and deleted after encoding.

---

## 3. Requirements

### Python packages

```
gpxpy
contextily
matplotlib
numpy
pyproj
```

### System
- `ffmpeg` available on `PATH` (used for MP4 encoding).

### Environment
- Designed to run under **`uv`**.
- Should also work with plain `pip` / `venv`.
- Installed as a package, so the entry point is `gpx-animate` (`uv sync`, then
  `uv run gpx-animate ...`; a released version would be `uvx gpx-animate ...`).

---

## 4. Usage

### Default
```bash
uv run gpx-animate my_trip.gpx
```
Produces `my_trip.mp4` next to the GPX file.

### Examples

```bash
# Outdoor / hiking look for YouTube (16:9)
uv run gpx-animate my_trip.gpx --style topo --out topo.mp4

# Square for Medium / Instagram
uv run gpx-animate my_trip.gpx --size 1:1 --out square.mp4

# Vertical for Shorts / Reels, with a watermark
uv run gpx-animate my_trip.gpx --size 9:16 \
    --logo brand.png --logo-position top-left
```

### CLI flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `gpx` | path (positional) | — | Input GPX file |
| `--style` | enum | `topo` | `osm`, `topo`, `satellite`, plus `positron`/`voyager`/`dark` when `CARTO_API_KEY` is set |
| `--duration` | float (s) | `5.0` | Length of the drawing phase |
| `--hold` | float (s) | `1.0` | Pause on the finished trace |
| `--fps` | int | `30` | Frame rate |
| `--size` | enum | `16:9` | `16:9`, `1:1`, `9:16` |
| `--out` | path | `<gpx_stem>.mp4` | Output file |
| `--logo` | path | `None` | PNG with transparency |
| `--logo-position` | enum | `bottom-right` | `bottom-right`, `bottom-left`, `top-right`, `top-left` |
| `--margin` | float | `0.08` | Fractional margin around the track bounding box |
| `--log-level` | enum | `info` | `debug`, `info`, `warning`, `error` |

Total clip length = `duration + hold` (default **6 s**: 5 s drawing + 1 s hold).

---

## 5. Configuration

Defaults live in frozen dataclasses — `RenderConfig` and `Style` in
`gpx_animate.domain`, composed by `gpx_animate.config.defaults` — so they are
typed, immutable, and validated at construction.

### Key config fields

**Map appearance**
- `style` — basemap preset (see `STYLES` dict).
- `margin` — fractional margin around the track bounding box (`--margin`).

**Animation timing**
- `duration` — drawing phase, seconds.
- `hold` — hold phase, seconds.
- `fps` — frame rate.

**Output**
- `size` — one of `SIZES` (`16:9`, `1:1`, `9:16`).
- `dpi` — render DPI.
- `out` — output path (`None` → derived from GPX filename).

**Look & feel**
- `bg_color`, `track_faint`, `track_bright`, `marker_color`, `hud_color`, `title_color`
- `font`
- `logo`, `logo_position`

### Extensibility
- **New basemap:** add one entry to `TILE_PROVIDERS` in
  `gpx_animate.adapters.basemaps.tiles`.
- **New aspect ratio:** add one entry to `SIZE_PRESETS` in
  `gpx_animate.domain.render_config`.
- **New CLI flag:** add to `build_parser()`; the override is applied
  automatically, there is no whitelist to update.

### Precedence
```
domain defaults  <  CLI flags
```
Overrides are applied with `dataclasses.replace`, which re-runs validation, so
an invalid flag value is rejected before any rendering happens.

---

## 6. Design decisions (and rationale)

1. **Matplotlib, not QGIS.**
   QGIS produces prettier cartography out of the box, but PyQGIS headless
   rendering is fragile across versions and slow for hundreds of frames. The
   goal here is a reproducible content pipeline, not a map-design tool.

2. **contextily for basemaps.**
   One line to drop tiles under a projected track. Lets the "look" be a
   parameter rather than a project file.

3. **Frame-by-frame PNG → ffmpeg.**
   Chosen over `matplotlib.animation` because it gives precise control over the
   hold phase, frame count, and encoding parameters (CRF, preset, pixel format).
   Also easier to inspect a single frame when debugging.

4. **HUD updates live.**
   Distance and elevation track the head of the line. Turns the clip into a
   small data story, not just a moving dot.

5. **Hold phase as extra frames at `t=1.0`.**
   No ffmpeg gymnastics, no duplicate logic. The last N frames are simply the
   final state.

6. **Temp dir for frames.**
   Keeps the workspace clean on re-runs. A `--keep-frames` flag can be added
   trivially if debugging requires it.

7. **Frozen config dataclasses + CLI override.**
   Branding changes shouldn't require touching logic. A creator changes colors
   once, and every future trip inherits them. Immutability plus `__post_init__`
   validation means a bad value fails immediately instead of mid-render.

---

## 7. Known limitations

- **No Douglas-Peucker simplification** yet. Very large GPX files (10k+ points)
  render slowly and produce large frames. Planned for v2.
- **No elevation subplot.** Only the map is animated.
- **No speed-based coloring.** Single color for the growing line.
- **No audio.** Music must be muxed separately with ffmpeg.
- **No batch mode.** One GPX per invocation (a shell loop works fine).
- **Projection is hard-coded to Web Mercator.** Fine for contextily tiles; would
  need changing for other tile sources.
- **One polyline per file.** Every track and every segment in the GPX is
  concatenated into a single line, so a multi-segment file is not animated as
  separate legs. Waypoints are not read at all.

---

## 8. Roadmap (candidate v2 items)

1. Douglas-Peucker simplification (`--simplify`).
2. Animated elevation profile subplot.
3. Speed-gradient coloring along the track.
4. Intro/outro fade via ffmpeg filters.
5. Batch mode: `for g in trips/*.gpx; do gpx-animate "$g"; done`.
6. Optional background music muxing.
7. `--keep-frames` debug flag.
8. Preset "brands" (e.g. `--brand hiking`, `--brand city`) as named configs.

---

## 9. Verification checklist

For a reviewer (human or AI) checking this spec against the implementation:

- [ ] `RenderConfig`/`Style` defaults contain all documented keys.
- [ ] Every config key can be overridden by the corresponding CLI flag
      listed in §4 (where a flag exists).
- [ ] `STYLES` contains exactly: `positron`, `voyager`, `dark`, `osm`, `topo`, `satellite`.
- [ ] `SIZES` contains exactly: `16:9`, `1:1`, `9:16`.
- [ ] Clip length equals `duration + hold` (±1 frame).
- [ ] Final frame is held for `hold` seconds.
- [ ] Output is H.264, `yuv420p`, playable in a browser.
- [ ] Output filename defaults to `<gpx_stem>.mp4` in the GPX directory.
- [ ] Frames are written to a temp dir and cleaned up.
- [ ] Missing `ffmpeg` produces a clear error, not a traceback.
- [ ] Missing/invalid GPX produces a clear error.
- [ ] No global state mutated between runs.

---

## 10. Environment notes

- **Primary runner:** `uv`.
- Suggested `pyproject.toml` extras if the script is later packaged:
  ```toml
  [project]
  name = "gpx-animate"
  requires-python = ">=3.11"
  dependencies = [
    "gpxpy",
    "contextily",
    "matplotlib",
    "numpy",
    "pyproj",
  ]
  ```
- ffmpeg is a system dependency, not a Python one; document it in the runner
  environment (e.g. via `uv tool` notes or a `Makefile`).

---

## 11. Glossary

- **GPX** — GPS Exchange Format; XML with tracks, routes, waypoints.
- **Track** — a recorded path with timestamps and elevation.
- **Hold phase** — the pause at the end of the animation where the full trace
  is visible but nothing moves.
- **Web Mercator (EPSG:3857)** — the projection used by virtually all web tile
  basemaps; needed for contextily.
- **CRF** — Constant Rate Factor; ffmpeg quality knob (lower = better).
