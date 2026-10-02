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
  ├─ basemap                     → tiles, a GeoTIFF, or a flat colour under the track
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

# Vertical for Shorts / Reels, with start- and end-point logos
uv run gpx-animate my_trip.gpx --size 9:16 \
    --logo-start brand.png --logo-end brand.png
```

### CLI flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `gpx` | path (positional) | — | Input GPX file |
| `--style` | enum | `topo` | `osm`, `topo`, `satellite`, plus `positron`/`voyager`/`dark` when `CARTO_API_KEY` is set, or `none` for no map |
| `--tiff` | path | — | Local GeoTIFF to draw instead of tiles; wins over `--style` |
| `--duration` | float (s) | `5.0` | Length of the drawing phase |
| `--hold` | float (s) | `1.0` | Pause on the finished trace |
| `--fps` | int | `30` | Frame rate |
| `--size` | enum | `16:9` | `16:9`, `1:1`, `9:16` |
| `--out` | path | — | Output file; suffixed if it exists unless `--force` |
| `--force` | flag | off | Overwrite `--out` instead of suffixing it |
| `--logo-start` | str | `None` | Logo at the start point: a registry name or an image path |
| `--logo-end` | str | `None` | Logo at the end point, same resolution |
| `--logo-marker` | str | `None` | Logo that rides the moving head marker |
| `--logo-size` | int | — | Override logo width in device pixels, for every placement |
| `--logo-registry` | path | `./logos/registry.yaml` | YAML registry mapping names to logo files |
| `--margin` | float | `0.15` | Fractional margin around the track bounding box |
| `--bounds` | str | — | Fixed view `min_lon,min_lat,max_lon,max_lat` in degrees; overrides `--margin` |
| `--log-level` | enum | `info` | `debug`, `info`, `warning`, `error` |

Total clip length = `duration + hold` (default **6 s**: 5 s drawing + 1 s hold).

### Framing

By default the view is the track's bounding box, padded by `--margin`. For a
fixed window instead, give the four corners in degrees:

```
uv run gpx-animate my_trip.gpx --bounds 2.35,48.85,2.40,48.90
```

`--bounds` replaces the margin-derived view entirely (the track need not reach
the frame edges), and is rejected up front if the corners are reversed or
outside `[-180, 180]` × `[-90, 90]`.

### Logos

`--logo-start`, `--logo-end` and `--logo-marker` place a PNG at the trip's start
point, end point and moving head. Each source is either a path to an image or a
name from the logo registry (default `./logos/registry.yaml`, overridable with
`--logo-registry`). A path wins over a name of the same spelling. Registry
entries may also set placement defaults, and a relative `file:` is resolved
against the registry's own directory:

```yaml
# logos/registry.yaml
logos:
  bike:
    file: bike.png          # -> logos/bike.png
    anchor: bottom          # center (x), bottom (y); default anchor: center
    default_size_px: 96     # width in device pixels; default 48
```

Anchors are named as *side on x* and *side on y* from `left`, `center`, `right`
and `above`, `center`, `below`. The image keeps its aspect; `default_size_px`
is the width.

Every visible logo sits on a rounded white plate so it reads even over busy
terrain. `--logo-size <px>` overrides the size for **all** placements at once
(registry sizes describe the logo, the flag describes one render):

```
uv run gpx-animate my_trip.gpx --logo-marker car --logo-size 192
```

A fully transparent image draws nothing at all.

### Where the video goes

Without `--out`, the name is generated so no two runs can collide:

```
./output/<gpx_stem>__<YYYYMMDD-HHMMSS>.mp4     e.g. output/trip__20260927-140233.mp4
```

`./output/` is created if missing. An explicit `--out` is honoured, but if that
file already exists it becomes `--out__2`, `--out__3`, … instead of being
replaced; `--force` restores the overwrite. The suffix is inserted before the
extension, so `trip.mp4` becomes `trip__2.mp4`.

### Choosing a basemap

Three sources, picked in this order:

1. `--tiff map.tif` — a GeoTIFF you supply. Nothing is downloaded.
2. `--style none` — no map at all, just the background colour.
3. `--style osm|topo|satellite` — tiles from the given provider (default `topo`).

```bash
uv run gpx-animate my_trip.gpx --tiff alps.tif     # your own imagery
uv run gpx-animate my_trip.gpx --style none         # no map, no network
```

`--tiff` overrides `--style` whichever order they appear in, and either can be
set in a config file (`tiff = "alps.tif"`, `style = "none"`).

The GeoTIFF is reprojected into the render's Web Mercator frame if it is in
another projection, and its whole file is read, so crop a large raster down
first. It has to overlap the area being rendered: point `--tiff` at the wrong
part of the world and you get a clear error rather than a blank frame. It must
also declare a CRS.

---

## 5. Configuration

Settings are typed and immutable: `RenderConfig` and `Style` in
`gpx_animate.domain`, validated at construction. Five layers stack, and each
one only overrides the layer below it:

```
domain defaults  <  ~/.config/gpx-animate/config.toml  <  ./gpx-animate.toml
                 <  GPX_ANIMATE_* environment  <  CLI flags
```

Overrides are applied with `dataclasses.replace`, which re-runs validation, so
a bad value is rejected before anything renders.

### Every key

`output_dir`, `dpi` and the `appearance.*` keys have no CLI flag; they are set in
a config file or the environment.

| Key | Type | Default | What it does |
|---|---|---|---|
| `style` | str | `topo` | Basemap preset, see `TILE_PROVIDERS`; `none` draws no map |
| `tiff` | path | *(none)* | Local GeoTIFF to draw instead of tiles; wins over `style` |
| `duration` | float | `5.0` | Drawing phase, seconds |
| `hold` | float | `1.0` | Hold phase after the trace is finished, seconds |
| `fps` | int | `30` | Frame rate for both phases |
| `size` | str | `16:9` | `16:9`, `1:1` or `9:16` |
| `margin` | float | `0.15` | Padding around the track bbox, as a fraction |
| `bounds` | str | *(none)* | Fixed view `min_lon,min_lat,max_lon,max_lat`; wins over `margin` |
| `out` | path | *(none)* | Output file; blank means "generate one" |
| `output_dir` | path | `output` | Where the generated name goes |
| `force` | bool | `false` | Overwrite `out` instead of suffixing it |
| `logo_start` | str | *(none)* | Logo at the start point: a registry name or a path |
| `logo_end` | str | *(none)* | Logo at the end point, same resolution |
| `logo_marker` | str | *(none)* | Logo that rides the moving head marker |
| `logo_size_px` | int | *(none)* | Override logo width in device pixels, for every placement |
| `appearance.bg_color` | str | `#f5f5f2` | Figure background |
| `appearance.track_faint` | str | `#b8b8b8` | The whole track, before it is drawn |
| `appearance.track_bright` | str | `#e63946` | The part drawn so far |
| `appearance.marker_color` | str | `#1d3557` | The moving head marker |
| `appearance.hud_color` | str | `#1d3557` | Distance/elevation readout |
| `appearance.title_color` | str | `#1d3557` | Trip title |
| `appearance.font` | str | `DejaVu Sans` | Font family |

### The two TOML files

`./gpx-animate.toml` is per-project and worth committing. The user file applies
everywhere. Both are optional, and a missing file is not an error.

```toml
# gpx-animate.toml
style = "osm"
duration = 8.0
output_dir = "renders"
force = true

[appearance]
track_bright = "#ff5a1f"
font = "Inter"
```

### The environment layer

Any key can be set as `GPX_ANIMATE_<KEY>`, with the `appearance.` prefix
dropped and dots becoming underscores:

```bash
GPX_ANIMATE_DURATION=8.0 gpx-animate trip.gpx
GPX_ANIMATE_APPEARANCE_TRACK_BRIGHT="#ff5a1f" gpx-animate trip.gpx
```

Useful in CI, where a committed file you would rather not change is the
problem. An empty value means "unset", so `GPX_ANIMATE_OUT=` reverts to the
generated name.

### Unknown keys are errors

A typo is reported at startup with the list of valid keys, rather than
silently ignored:

```
$ gpx-animate trip.gpx
gpx-animate.toml has no setting 'durtaion'; valid keys are style, duration, hold, ...
```

The same holds for a `GPX_ANIMATE_*` variable that names nothing. The prefix is
this tool's own, so nothing outside it should ever be there.

### Extensibility
- **New basemap:** add one entry to `TILE_PROVIDERS` in
  `gpx_animate.adapters.basemaps.tiles`; it becomes a `--style` choice
  automatically, and key-gated entries are only listed when their variable is
  set.
- **New aspect ratio:** add one entry to `SIZE_PRESETS` in
  `gpx_animate.domain.render_config`.
- **New CLI flag:** add to `build_parser()`; the override is applied
  automatically, there is no whitelist to update.
- **New config key:** add the field to `RenderConfig` or `Style`. Every layer
  is validated against the dataclass fields, so it becomes settable in both
  files and the environment with no further work.

---

## 6. Design decisions (and rationale)

1. **Matplotlib, not QGIS.**
   QGIS produces prettier cartography out of the box, but PyQGIS headless
   rendering is fragile across versions and slow for hundreds of frames. The
   goal here is a reproducible content pipeline, not a map-design tool.

2. **contextily for basemaps, and rasterio for `--tiff`.**
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
