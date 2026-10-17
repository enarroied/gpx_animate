# GPX-Animate — Project Specification & Agent Brief

> This document is the **source of truth** for the project. Any AI agent working on
> this repo must read it fully before touching code, and must update it when scope
> changes. It defines architecture, tooling, workflows, and the concrete user
> stories to implement.

---

## 0. One-line pitch

Turn a GPX file into a short, animated, brandable MP4 with either a CLI tool or a
GUI, both driving the same engine — with a clean, testable, hexagonal Python
codebase.

---

## 1. Product goals

1. **Two front ends, one engine**: `gpx-animate trip.gpx` for scripts and
   terminals, `gpx-animate-gui` for people who would rather click. Both are
   permanent and neither wraps the other; both call the same composition root.
2. **No logic duplication**: a feature added to the CLI is reachable from the
   GUI by construction, and a test enforces it (US-8).
3. **Visual variety**: basemaps (tiles, no-map, local GeoTIFF, hillshade, 3D).
4. **Brandable**: logos at start/end/moving; fonts, colors, title all parameterized.
5. **Reproducible**: deterministic renders, timestamped outputs, no overwrites.
6. **Agent-friendly**: an AI agent should be able to add features by reading this doc + tests.

---

## 2. Non-goals (for v1)

- No web app, no server, no accounts.
- No music/audio muxing (can be added later via ffmpeg wrapper).
- No real-time preview of the animation (GUI shows stills, not playback).
- No cloud rendering.

---

## 3. Architecture — Hexagonal (Ports & Adapters)

```
┌─────────────────────────────────────────────────────────────┐
│  Adapters (I/O, frameworks, third parties)                  │
│  ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐  │
│  │  CLI      │  │  PyQt GUI │  │ Basemap  │  │  ffmpeg   │  │
│  │ (click)   │  │           │  │  providers│ │  encoder  │  │
│  └─────┬─────┘  └─────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│        │              │             │              │        │
│  ┌─────▼──────────────▼─────────────▼──────────────▼─────┐  │
│  │              Application (use cases)                  │  │
│  │  RenderAnimation · LoadTrack · ResolveOutput · Export │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────▼─────────────────────────────────┐  │
│  │                    Domain (pure)                      │  │
│  │  Track · Point · Style · RenderConfig · Bbox · Logo   │  │
│  │  (no I/O, no matplotlib, no requests)                 │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Rules:**

- **Domain** has zero dependencies on matplotlib, requests, PyQt, ffmpeg.
- **Application** orchestrates domain + ports; no framework imports either.
- **Adapters** implement ports (basemap fetch, frame renderer, video encoder, CLI, GUI).
- **Ports** are abstract interfaces (`Protocol` classes) defined in `application/ports.py`.

Concrete package layout:

```
src/gpx_animate/
├── domain/
│   ├── track.py            # Track, Point, haversine, cumulative distance
│   ├── style.py            # Style dataclass (colors, fonts)
│   ├── render_config.py    # RenderConfig, GifConfig, SIZE_PRESETS, PROFILE_POSITIONS
│   ├── logo.py             # Logo anchors and sizes
│   └── bbox.py             # pure bounds arithmetic (no rasterio)
├── application/
│   ├── ports.py            # Protocols: TrackLoader, BasemapProvider, FrameRenderer,
│   │                       #   Encoder, GifEncoder, LogoLoader
│   ├── use_cases/
│   │   ├── load_track.py
│   │   ├── render_animation.py
│   │   ├── export_video.py
│   │   └── resolve_output.py
│   └── errors.py
├── adapters/
│   ├── basemaps/
│   │   ├── tiles.py        # contextily-based
│   │   ├── tiff.py         # rasterio
│   │   ├── none.py         # blank background
│   │   └── factory.py      # --style / --tiff dispatch
│   ├── renderers/
│   │   ├── matplotlib_renderer.py  # map frames + chart inset
│   │   ├── elevation_chart.py      # shared chart drawing + geometry
│   │   └── profile_renderer.py     # standalone chart video
│   ├── encoders/
│   │   ├── ffmpeg_encoder.py
│   │   └── gif_encoder.py   # Pillow
│   ├── logos/
│   │   └── registry.py     # reads logos/registry.yaml
│   ├── cli/
│   │   └── main.py         # argparse
│   ├── pipeline.py         # the composition root both front ends call
│   └── gui/                # PyQt
│       └── main.py
└── config/
    ├── defaults.py         # default_config() -> RenderConfig
    ├── layers.py           # one layer: defaults / user / project / env
    └── loader.py           # reads + coerces those layers
```

Not yet built, listed here so the target layout is unambiguous: a DEM-based
`basemaps/hillshade.py` (M9, separate spec).
```

---

## 4. Tooling & Workflow

### 4.1 Package manager
- **uv** for everything: `uv run`, `uv add`, `uv sync`, `uv tool`.

### 4.2 Linting & formatting — Ruff (strict)

`pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py310"
src = ["src"]
# ruff 0.16 also formats Python blocks inside Markdown; this doc is
# hand-authored, so keep the formatter off it.
extend-exclude = ["*.md"]

[tool.ruff.lint]
select = ["E","W","F","I","UP","PTH","B","C4","SIM","RET","PL","N"]
ignore = ["E501","PLR0913","PLR0917","PLR2004"]

[tool.ruff.lint.per-file-ignores]
# Projected X/Y in the renderer; Qt's camelCase overrides in the GUI.
"src/gpx_animate/adapters/renderers/matplotlib_renderer.py" = ["N806"]
"src/gpx_animate/adapters/gui/main.py" = ["N802"]

[tool.ruff.lint.isort]
force-single-line = true
combine-as-imports = true
lines-after-imports = 2

[tool.ruff.lint.pydocstyle]
convention = "google"
```

- **First commit** on any new branch: add this config, run `uv run ruff format .` and
  `uv run ruff check --fix .`, commit as `chore: add ruff and format`.

### 4.3 Type checking — `ty` (not mypy)
- Install via `uv add --dev ty`
- Run `uv run ty check src tests` in CI and pre-commit.

### 4.4 Other dev tools
- `pip-audit` — dependency vulnerability scan.
- `vulture` — dead code detection (`--min-confidence 80`).
- `pytest` + `pytest-cov` — tests and coverage.
- `pre-commit` — hooks.

### 4.5 Pre-commit config

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff
        name: ruff
        entry: uv run ruff check --fix
        language: system
        types: [python]
      - id: ruff-format
        name: ruff-format
        entry: uv run ruff format
        language: system
        types: [python]
      - id: ty
        name: ty
        entry: uv run ty check src tests
        language: system
        pass_filenames: false
        always_run: true
      - id: vulture
        name: vulture
        entry: uv run vulture src tests --min-confidence 80
        language: system
        pass_filenames: false
        always_run: true
      - id: pytest
        name: pytest
        entry: uv run pytest -q
        language: system
        pass_filenames: false
        always_run: true
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

### 4.6 CI (GitHub Actions)
- `.github/workflows/ci.yml`: uv install → ruff → ty → vulture → pytest → coverage upload.
- `.github/workflows/codecov.yml` or inline Codecov step with badge in README.
- Matrix: Python 3.11 and 3.12 on Ubuntu.

### 4.7 Branching & commit workflow (for agents)
1. `chore:` add tooling (ruff, ty, pre-commit) — **separate commit, merge before anything else**.
2. `test:` add pytest scaffolding + first tests for current code — **before refactor**.
3. `refactor:` split into hexagonal layers — **tests must still pass**.
4. `feat:` add the actual feature.
5. Never mix `refactor` and `feat` in the same commit.

---

## 5. Configuration

- **Single source of defaults**: `src/gpx_animate/config/defaults.py`.
- **Override layers (in order):**
  1. Defaults
  2. `~/.config/gpx-animate/config.toml` (user)
  3. Project-local `gpx-animate.toml`
  4. Environment variables (`GPX_ANIMATE_*`)
  5. CLI flags / GUI widgets (highest priority)
- **Defaults are frozen dataclasses**, not a dict — `RenderConfig` and `Style`
  fields, composed by `default_config()`. Overrides go through
  `dataclasses.replace`, which re-runs `__post_init__` validation, so a bad
  override is rejected where it is written rather than at render time.
- Nested groups are TOML tables and env-var sub-keys, e.g. `gif.colors` lives in
  `[gif]` in the toml layers and in `GPX_ANIMATE_GIF_COLORS` in the environment.
- The settable-key set is **derived** from the dataclass fields, not hand-listed,
  so a new domain field is settable in both the files and the environment with no
  second list to keep in sync. Unknown keys are errors: a typo like `durtaion` is
  reported with the list of valid keys, never ignored.
- Every config key must be documented in `README.md` and referenceable by an agent.

---

## 6. AGENTS.md (required in repo root)

Must contain, at minimum:

- **Clean code is non-negotiable.** Explain what "clean" means here: single
  responsibility, no side effects in domain, typed signatures, docstrings
  (Google style), no magic numbers outside `config/`.
- **Tests as you go.** Any PR that adds a function must add tests. No exceptions.
- **Hexagonal boundaries.** Domain cannot import adapters. Application cannot
  import PyQt or matplotlib directly — only through ports.
- **Ruff + ty + vulture + pytest must pass** before any commit.
- **Update this spec** when scope changes; do not silently diverge.
- **Naming**: files, classes, functions — follow PEP 8, be explicit, no abbreviations
  (`cfg` is fine as a local, `configuration` in public APIs).
- **Logging over printing** in library code; CLI uses a logger adapter.

---

## 7. User stories (implementation backlog)

### US-1 — Project scaffolding & tooling
**As a** maintainer, **I want** the repo to have uv, ruff, ty, vulture, pytest,
pre-commit, and CI configured **so that** every future change is validated.

**Acceptance criteria:**
- `uv sync` installs everything.
- `uv run ruff check .` passes.
- `uv run ty check src tests` passes.
- `uv run pytest` runs (even with 0 tests initially).
- `pre-commit run --all-files` passes.
- CI badge in README.

### US-2 — Hexagonal refactor
**As a** maintainer, **I want** the monolithic script split into
`domain/`, `application/`, `adapters/` **so that** a GUI can be added later
without touching logic.

**Acceptance criteria:**
- No file in `domain/` imports matplotlib, requests, PyQt, contextily, ffmpeg.
- `application/ports.py` defines: `BasemapProvider`, `FrameRenderer`,
  `Encoder`, `LogoLoader`.
- CLI is an adapter; it wires dependencies and calls use cases.
- Existing behavior (render MP4 from GPX) unchanged.
- Every domain function has a unit test.

### US-3 — Test suite
**As a** maintainer, **I want** comprehensive tests **so that** refactors are safe.

**Required test coverage:**
- `domain/track.py`: distance (haversine correctness on known pairs),
  cumulative distance, elevation gain, empty track, single-point track,
  duplicate points.
- `domain/render_config.py`: validation (fps > 0, durations > 0, valid size key),
  total duration = draw + hold.
- `application/use_cases/load_track.py`: parses a fixture GPX, raises on empty,
  raises on malformed XML.
- `application/use_cases/render_animation.py`: with a fake renderer port,
  asserts the correct number of frames and that the last N are held.
- Adapters: mocking `contextily`, `requests`, `subprocess` for ffmpeg.
- Fixtures in `tests/fixtures/` — small GPX files (10–50 points), a tiny PNG logo.

**Coverage target:** ≥ 85% on `domain/` and `application/`, no target on adapters.

### US-4 — Timestamped outputs (no overwrites)
**As a** content creator, **I want** each run to write to a unique file **so that**
I don't accidentally destroy a previous render.

**Acceptance criteria:**
- Default output dir: `./output/` (created if missing).
- Filename pattern: `<gpx_stem>__<YYYYMMDD-HHMMSS>.mp4`.
- `--out` still honored if provided; if it exists, suffix `__2`, `__3`, … unless
  `--force` is passed.

### US-5 — Logo system
**As a** content creator, **I want** to place logos at start, end, or as a moving
marker **so that** I can brand my videos.

**Acceptance criteria:**
- `logos/` folder with a `registry.yaml`:

  ```yaml
  logos:
    car:
      file: car.png
      anchor: center
      default_size_px: 48
    walking_man:
      file: walking_man.png
      anchor: bottom
      default_size_px: 40
  ```

- CLI flags:
  - `--logo-start <name|path>` — placed at track start, static.
  - `--logo-end <name|path>` — placed at track end, static.
  - `--logo-marker <name|path>` — moves with the head of the growing line.
- All three accept either a name from the registry or a direct file path.
- Missing file → clear error, non-zero exit.
- Tests: registry parsing, flag resolution, missing-file error, default-none behavior.

### US-6 — Basemap abstraction
**As a** content creator, **I want** to pick from tiles, a local TIFF, hillshade,
or no map **so that** I control the look and don't depend on flaky servers.

**Acceptance criteria:**
- `BasemapProvider` protocol: `get_image(bbox, crs, zoom) -> (ndarray, extent)`.
- Implementations:
  - `tiles` — contextily, with all currently supported styles.
  - `tiff` — via `rioxarray`/`rasterio`, takes a path to a GeoTIFF.
  - `none` — solid background color.
  - `hillshade` — DEM + hillshade (may be v2).
- `--style` accepts built-in names; `--tiff <path>` selects TIFF provider.
- Tests: TIFF provider with a tiny fixture GeoTIFF (10×10 px) — asserts extent
  and shape; `none` returns correct color.

### US-7 — Boundary control
**As a** content creator, **I want** to choose between fixed bounds and a
percentage margin **so that** I can either frame tightly or show context.

**Acceptance criteria:**
- `--margin 0.15` (default) — minimum fractional padding around the track bbox.
- `--bounds min_lon,min_lat,max_lon,max_lat` — overrides margin.
- Both are part of `RenderConfig`.
- **The view is fitted to the output frame's aspect** after the margin is applied
  (or from `--bounds`, which skips the margin). The shorter axis is grown about
  the centre so `width / height` equals the frame's, and nothing is ever cropped
  or shrunk. The axes is left at matplotlib's default `aspect="auto"`, which
  stretches whatever shape it is handed to fill the frame, so matching the ratios
  is what stops a tall track being drawn several times too wide in a 16:9 frame —
  and its basemap being upsampled to match. `Bbox.fit_aspect(aspect)` in
  `domain/bbox.py` does the growth; it is expand-only and idempotent and is
  applied to an explicit `--bounds` window too. (Tile-zoom/sharpness is separate
  and unfixed; this only removes the distortion.)
- Tests: bounds parsing, margin math, invalid bounds rejected, and the fitted
  view's aspect matching every size preset for both narrow and wide tracks.

### US-8 — PyQt GUI
**As a** user, **I want** a small GUI to pick a GPX, style, colors, logos, and
hit "Render" **so that** I don't have to remember CLI flags.

The GUI is a **peer** of the CLI, not a phase that replaces it. `gpx-animate`
stays first-class for scripts and terminals, and nothing is deprecated. The
point of the hexagonal split is that this is *possible* without duplicating
logic, and the acceptance criteria below are what stop it decaying into a
wrapper.

**Acceptance criteria:**
- `gpx-animate-gui` launches (an optional extra installs PyQt6; the CLI stays
  Qt-free and installable without it).
- Widgets: file picker, style dropdown, duration/hold spinboxes, size dropdown,
  color pickers, logo pickers, output dir, Render button, log pane, GIF and
  elevation-chart settings.
- **Every** `RenderConfig` field is settable from a widget. Enforced per field
  by a test, not by review, because a flag added without a spinbox is otherwise
  invisible.
- Calls the **same** composition root as the CLI, asserted by function-object
  identity; never a subprocess.
- Reads the same config layers (defaults, user TOML, project TOML, environment),
  seeding the widgets from them.
- Renders off the GUI thread and reports failures in the log pane rather than a
  traceback.
- Tests: headless `pytest-qt` coverage, offscreen, no display required.

### US-9 — Agent-readiness
**As an** AI agent, **I want** the repo to be self-describing **so that** I can
add features without breaking things.

**Acceptance criteria:**
- `AGENTS.md` in root with the rules from §6.
- This spec document (`SPECS.md`) in root.
- Every public function has a Google-style docstring.
- Every config key has a one-line docstring or comment.
- `README.md` includes: install, CLI usage, config reference, architecture diagram.

### US-10 — GIF export alongside the MP4
**As a** content creator, **I want** the same animation delivered as an animated
GIF **so that** I can embed it where video is not supported (blog posts, issue
trackers, chat).

**Sizing principle:** the GIF is a *downgrade* of the video, never a second
render at video quality. A GIF at MP4 resolution and 256 colors routinely lands
in the tens of megabytes for a few seconds of animation, which is slow to
encode, slow to upload, and slow for a reader to load. Every knob below exists
to keep it small.

**Defaults** — as the frozen `GifConfig` dataclass in `domain/render_config.py`,
composed into `default_config()` and overridable via the `[gif]` table in the
toml layers and per-flag on the CLI:

```python
@dataclass(frozen=True)
class GifConfig:
    enabled: bool = False
    size: str = "800x450"   # px, independent of the SIZES aspect presets
    fps: int = 15            # half the MP4 rate is fine
    colors: int = 256        # 64 | 128 | 256
    dither: bool = False     # off = smaller
    loop: int = 0            # 0 = infinite
```

**Acceptance criteria:**
- `enabled` defaults to `False`: no GIF is written unless asked. The MP4 is
  always produced, and **the MP4 encode is untouched** — CRF 18, `yuv420p`, full
  `dpi`. Every quality reduction applies to the GIF only.
- Implemented behind a new `GifEncoder` port (`application/ports.py`), with
  `PillowGifEncoder` (`adapters/encoders/gif_encoder.py`) as the adapter. The use
  case takes it as a keyword and imports no adapter; the CLI injects it and runs
  `require_pillow()` up front, so a missing Pillow is a one-line exit rather than
  a failure after the whole render. No duplicated frame logic.
- Encoded from the same PNG frames as the MP4, and before the temp dir is cleaned
  up. Order is **MP4, then the chart video if `--chart-video` was asked for, then
  the GIF** — the MP4 is the deliverable, so it is written first. The frames are
  **downscaled, not re-rendered** — a second render pass would cost more than it
  saves.
- `size` is honoured exactly as `WIDTHxHEIGHT`, independent of `SIZES`. Frames
  are scaled to *cover* the box and center-cropped (`ImageOps.fit`), so a `9:16`
  MP4 into an `800x450` GIF crops rather than distorts. Invalid or unparsable
  sizes are rejected with a clear error.
- `fps` samples every Nth rendered frame, `N = max(1, round(fps / gif.fps))`.
  A `gif.fps` greater than the MP4 `fps` is rejected — frames cannot be invented.
  Note that GIF stores frame delays in centiseconds, so 15 fps is written as
  70 ms (~14.3 fps effective); document the rounding rather than fight it.
- `colors` must be one of 64, 128, 256; anything else is rejected before
  rendering starts. Every frame is quantised against **one shared palette**, built
  from an evenly-spaced spread of the clip — *not* an adaptive palette per frame.
  Handing Pillow `palette=ADAPTIVE` on a multi-frame `save()` makes it quantise
  each frame separately but write only the first frame's table as the GIF's
  global one, so later frames decode against the wrong colours and a photographic
  basemap shifts hue mid-clip. Dithering therefore lives on the per-frame
  `quantize(palette=...)`, never on the `save()`.
- `dither` off uses `Image.Dither.NONE`; on uses the default dither. Dithering
  costs bytes, so the default is off.
- `loop = 0` means infinite.
- No audio, no alpha animation.
- The encode step logs one line with the result — path, byte size, frame count —
  so a size regression is visible without opening the file.
- Missing Pillow → clear error, non-zero exit, checked before rendering starts.
- Tests: output dimensions and center-crop, frame count and sampling, quantize
  palette size, dither on/off, loop value, `enabled = False` writes no file,
  invalid `size`/`colors`/`fps` rejected, and **MP4 encoder arguments unchanged
  when the GIF is enabled**.

### US-11 — Elevation chart as an overlay and a second video
**As an** viewer, **I want** the elevation profile visible while the track draws
**so that** I can see the climbs ahead of where the marker is, and — as an editor
— **I want** the chart as its own video **so that** I can cut it in separately.

**Acceptance criteria:**

- `--profile` places the chart over the map. Positions are `off`, `top`, `bottom`,
  `top-left`, `top-right`, `bottom-left`, `bottom-right`.
- `--profile-width` and `--profile-height` size it as fractions of the frame.
  The `top` and `bottom` strips span the full width and therefore **ignore**
  `--profile-width`; only the corner panels are width-constrained.
- **The whole curve is drawn once, with a cursor indicating progress.** This is
  intended behaviour, not a shortcut: the chart is a static readout of the shape
  being travelled, with a moving indicator, so nothing needs recomputing per frame
  except the cursor's position. Axes are therefore fixed to the full track and the
  profile never rescales mid-animation. A progressive reveal — clipping the curve
  to the current distance so it builds up — is a *different* design and is not
  what ships; if it is ever wanted it is a change to this section, not a bug fix.
- `PROFILE_POSITIONS` in `domain/render_config.py` is the single source of truth
  for allowed values, as a **mutable dict** of `position -> (loc, x_anchor,
  y_anchor)`. Validation, `--profile`'s choices and the geometry all read from it,
  so adding a position needs no edit elsewhere. It is a dict on purpose: the two
  anchors are read independently so a corner needs no special-casing, a centre
  anchor centres the panel, and tests `setitem` a middle-anchored entry to pin that
  centring rule. `FULL_WIDTH_PROFILE_POSITIONS` picks out the strips that span the
  frame.
- `--chart-video` **also** writes the chart as its own video, independently of
  `--profile` — either, both, or neither are valid.
- The sibling is named `<stem>-chart<suffix>`, derived rather than run through
  `resolve_output`, so a numbered main render does not consume a second number and
  an existing chart is overwritten rather than pushed aside.
- **The two videos must be frame-lockable**, which is the point of the second
  video. `revealed_point_count(index, n_draw_frames, n_total)` is shared by both
  renderers — a test asserts the map renderer uses the *same function object*,
  since behaviour-identical copies would pass every frame-count test while quietly
  drifting. Same size, dpi, fps, duration and hold for both.
- Drawing lives once, in `adapters/renderers/elevation_chart.py`, used both as an
  inset over the map and as the body of a standalone `ProfileRenderer`. Only the
  geometry differs. Three `inset_axes` traps make the sharing worth it, all
  silent: `from_any(0.28)` is 0.28 *points* (use `"28%"`), a child sized twice
  squares the fraction, and `tight_layout()` refuses to lay out insets at all — so
  the inset is created after it has run.
- The panel gets a backing plate. That is not decoration: drawn straight over tile
  texture with no plate, a hairline curve is effectively invisible.
- Requesting a chart video without chart frames → `ChartFramesMissingError`,
  surfaced as a message and exit code 1.
- Tests: each position's anchors and rect, full-width strips ignoring
  `--profile-width`, the whole-curve-plus-cursor contract, shared-helper identity,
  and both videos landing on the same moment per frame.

### US-12 — Hillshade & topographic overlay (M9, not yet implemented)
**As a** content creator, **I want** the terrain shaded under — or blended with —
the map **so that** relief reads at a glance and the track sits in the landscape
instead of on a flat web map.

This is a **design sketch**: M9 is not scheduled and no hillshade provider exists
yet. It records the shape the work should take and the traps a manual trial
already surfaced (see the notes at the end).

**Acceptance criteria (intended):**

- **Two distinct input semantics.** `--tiff PATH` stays as it is: pre-built
  imagery drawn unchanged. `--dem PATH` means *elevation values, shaded live*;
  `--dem auto` fetches the DEM tile for the view from a public source
  (Copernicus GLO-30 — see §12).
- **New elevation port + adapters.** `ElevationProvider.get_raster(bbox, crs) ->
  ElevationRaster` (ndarray + extent + crs), where `ElevationRaster` names no
  rasterio type — the same rule `BasemapImage` follows. `LocalDem` (a path) and
  `CopernicusDem` (`auto`, cached) implement it.
- **Shading is pure domain arithmetic** (`domain/hillshade.py`):
  `shade(elevation, *, pixel_size_x, pixel_size_y, azimuth, altitude, z_factor)
  -> uint8` in `0..255`. No I/O, so it stays domain-legal, and it is testable on
  synthetic planes (a flat DEM shades to a constant; a known slope matches the
  analytic value).
- **Slopes must be computed in metres, not degrees.** A DEM in EPSG:4326 uses
  degrees as horizontal units, so shading it directly gives latitude-dependent,
  wrong slopes. The elevation adapter warps to the frame's metric CRS
  (EPSG:3857) before shading; the `1/cos(lat)` y-stretch of 3857 is applied to
  the spacing. Whether a local UTM is worth the extra correctness is open (§12).
- **Composition, not a fork.** `HillshadeBasemap` is itself a `BasemapProvider`
  that wraps another provider as the colour underlay and multiplies the shade
  over it:
  - `--style none --dem …` → a grey hillshade (what `--tiff` on a pre-built
    hillshade gives today, but computed live);
  - `--style topo|osm --dem …` → the topographic overlay: tiles desaturated and
    lightened, then multiplied by the shade (the usual "terrain" look);
  - absent `--dem`, nothing changes — this is additive.
- **A grey hillshade ships as 3-band grey RGB**, because `imshow` paints an
  `(H, W, 1)` array through the colormap (viridis). That rule already exists in
  `TiffBasemap`.
- **Config surface.** `--dem`, `--hillshade-azimuth` (default 315),
  `--hillshade-altitude` (45), `--hillshade-z` (1.5) and `--hillshade-strength`
  (blend fraction, default 1.0). Each is a `RenderConfig` field, settable from
  files and the environment like every other key, and mirrored in the GUI — the
  field-parity test forces that.
- **Determinism & cost.** `auto` downloads at render time (network needed, as
  with tiles) and caches tiles under the XDG cache; a fixed local DEM gives
  byte-identical output for a fixed view.
- **Tests.** Domain `shade` on synthetic planes; a fake `ElevationProvider`; the
  blend over a fake tile image; a local DEM smaller than the view; one
  `integration`-marked test that `--dem auto` reaches AWS.
- **Out of scope:** 3D terrain (camera tilt, meshes), DEM mosaicking across
  tiles, and sampling elevation onto the track points.

**Notes from the manual trial (a pre-built hillshade through `--tiff`):**

- Copernicus GLO-30 is public on S3 (`copernicus-dem-30m`), no key; the flat URL
  404s because the real key carries a per-tile folder. One 30 m tile is ~42 MB
  and covers a whole Pyrenean trip.
- **Crop before reading.** The adapter reads whole files, so the DEM must be
  cropped to the fitted view plus a small buffer first; a multi-tile DEM would
  otherwise be a memory failure, not a slow render.
- **`gdaldem -combined` is a trap on GDAL 3.8.** It produces a 1-band grey, and a
  washed-out one (mean ~231/255); `-multidirectional` or a plain directional
  shade reads far better. The tool shades in numpy, so this is only a reminder
  that "combined" is not what its name suggests here.

---

## 8. Data model (domain, minimal)

```python
@dataclass(frozen=True)
class Point:
    lon: float
    lat: float
    elevation: float | None = None
    timestamp: datetime | None = None

@dataclass(frozen=True)
class Track:
    points: tuple[Point, ...]
    name: str

    def cumulative_distance_km(self) -> tuple[float, ...]: ...
    def elevation_gain_m(self) -> float: ...

@dataclass(frozen=True)
class GifConfig:
    """Deliberately low-quality GIF, independent of the MP4 render settings."""

    enabled: bool
    size: str          # "WIDTHxHEIGHT" px, e.g. "800x450"
    fps: int
    colors: int        # 64 | 128 | 256
    dither: bool
    loop: int          # 0 = infinite
    path: Path | None  # None -> <out_stem>.gif

@dataclass(frozen=True)
class RenderConfig:
    style: str
    duration: float
    hold: float
    fps: int
    size: str
    dpi: int
    margin: float
    bounds: tuple[float, float, float, float] | None
    logo_start: str | None
    logo_end: str | None
    logo_marker: str | None
    gif: GifConfig
    profile: str
    profile_width: float
    profile_height: float
    chart_video: bool
    # …colors, fonts, output_dir, force

@dataclass(frozen=True)
class Style:
    bg_color: str
    track_faint: str
    track_bright: str
    marker_color: str
    hud_color: str
    title_color: str
    font: str
```

Everything `frozen=True` unless profiling shows a reason otherwise.

---

## 9. CLI surface (target)

```
gpx-animate <gpx> [OPTIONS]

Options:
  --style TEXT              Built-in style name [positron|osm|topo|...|none]
  --tiff PATH               Local GeoTIFF as basemap (overrides --style)
  --dem PATH|auto           Elevation GeoTIFF, or 'auto' to fetch a public DEM
                            (Copernicus GLO-30, US-12, M9); shaded and blended
                            over --style. Not implemented yet.
  --hillshade-azimuth FLOAT Light direction, degrees clockwise from north [default: 315]
  --hillshade-altitude FLOAT Light elevation angle in degrees [default: 45]
  --hillshade-z FLOAT       Vertical exaggeration of the terrain [default: 1.5]
  --hillshade-strength FRAC How strongly the shade darkens the map [0..1; default: 1.0]
  --duration FLOAT          Drawing phase seconds [default: 5.0]
  --hold FLOAT              Hold phase seconds [default: 1.0]
  --fps INTEGER             [default: 30]
  --size [16:9|1:1|9:16]    [default: 16:9]
  --margin FLOAT            Bbox padding fraction [default: 0.15]
  --bounds TEXT             min_lon,min_lat,max_lon,max_lat (overrides margin)
  --logo-start TEXT         Logo name from registry or file path
  --logo-end TEXT
  --logo-marker TEXT
  --out PATH                Output file (default: ./output/<stem>__<ts>.mp4)
  --force                   Overwrite if --out exists
  --gif                      Also write a GIF (enables [gif] in config)
  --gif-size WIDTHxHEIGHT   GIF pixel box, independent of --size [default: 800x450]
  --gif-fps INTEGER         GIF frame rate, must be <= fps [default: 15]
  --gif-colors [64|128|256] GIF palette size [default: 256]
  --gif-dither / --no-gif-dither   [default: off]
  --gif-loop INTEGER        GIF loop count, 0 = forever [default: 0]
  --profile [off|top|bottom|top-left|top-right|bottom-left|bottom-right]
                             Elevation chart position [default: off]
  --profile-width FRAC      Chart width as fraction of frame width; ignored by the
                             full-width top and bottom strips [default: 0.28]
  --profile-height FRAC     Chart height as fraction of frame height [default: 0.15]
  --chart-video             Also write the elevation chart as its own video

  --log-level [DEBUG|INFO|WARNING|ERROR]
  --help
```

---

## 10. Milestones (suggested order for an agent)

1. **M0 — Tooling**: uv, ruff, ty, vulture, pre-commit, CI. Separate commit. ✅
2. **M1 — Tests first**: pytest scaffolding, tests for the current monolith. ✅
3. **M2 — Hexagonal refactor**: domain → application → adapters. Tests still green. ✅
4. **M3 — Timestamped outputs** (US-4). ✅
5. **M4 — Basemap abstraction** (US-6) + `--tiff` + `--style none`. ✅
6. **M5 — Logo system** (US-5). ✅
7. **M6 — Boundary control** (US-7). ✅
8. **M7 — SPECS.md + AGENTS.md polish** (US-9). ✅
9. **M8 — PyQt GUI** (US-8). ✅ Shipped as a second, equal front end; the CLI is
   unchanged and not deprecated.
10. **M9 — Hillshade / topographic overlay** (US-12, separate spec). Not started;
    the sketch is in US-12, and `--tiff` of a pre-built hillshade stands in
    meanwhile. Natural subtasks: domain shading → elevation port/adapters →
    `HillshadeBasemap` composition → CLI/config/GUI fields → docs.
11. **M10 — GIF export** (US-10). Independent of the other milestones; landed any
    time after M2, since it only needs the `Encoder` port. Shipped after M4 so the
    `none` basemap provider was available for cheap, fast test renders. ✅
12. **M11 — Elevation chart** (US-11). Like M10, independent of the ordered
    milestones above: it needs the frame renderer and nothing else new. ✅

✅ = landed and covered by tests.

---

## 11. Definition of Done (per milestone)

- All tests pass locally and in CI.
- Coverage threshold met for touched modules.
- Ruff, ty, vulture clean.
- Docstrings on new public APIs.
- `SPECS.md` and `AGENTS.md` updated if scope changed.
- Commit history is clean: `chore:` / `test:` / `refactor:` / `feat:` separated.

---

## 12. Open questions (for you to decide later)

Remaining items, with the current leaning — none is scheduled work yet.

- **Batch rendering.** Should the GUI support batch rendering (folder of GPX →
  folder of MP4)? Wanted for the future; a shell loop already covers the CLI.
- **DEM source for hillshade (M9).** The US-12 sketch leans on Copernicus GLO-30
  (`--dem auto`, public S3, no key, EPSG:4326 COG); SRTM/IGN remain alternatives.
  Open, and to be settled when M9 starts rather than now: shade in EPSG:3857
  (simple, needs the `1/cos(lat)` y-scale applied) or warp to a local UTM per
  view (correct slopes, more work). `--tiff` of a pre-built hillshade stands in
  meanwhile.
- **Moving logo per-vertex rotation.** Should the marker logo rotate to point
  along the bearing (e.g. a car)? Low priority, and **an option only** — the
  default stays upright.
- **Preview still.** Save the first and last frame alongside the MP4. Wanted, low
  priority, and cheap; should be **on by default** as an optional feature.
