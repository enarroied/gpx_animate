# GPX-Animate — Project Specification & Agent Brief

> This document is the **source of truth** for the project. Any AI agent working on
> this repo must read it fully before touching code, and must update it when scope
> changes. It defines architecture, tooling, workflows, and the concrete user
> stories to implement.

---

## 0. One-line pitch

Turn a GPX file into a short, animated, brandable MP4 (and eventually a GUI-driven
visual builder) — with a clean, testable, hexagonal Python codebase.

---

## 1. Product goals

1. **CLI-first**: `gpx-animate trip.gpx` produces a shareable MP4 in seconds.
2. **GUI-later**: The same core must power a PyQt app with no logic duplication.
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
│  │  RenderAnimation · LoadTrack · ResolveStyle · Export  │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────▼─────────────────────────────────┐  │
│  │                    Domain (pure)                      │  │
│  │  Track · Point · Frame · Style · RenderConfig         │  │
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
│   ├── track.py            # Track, Point, distance helpers
│   ├── style.py            # Style dataclass (colors, fonts, logo spec)
│   └── render_config.py    # RenderConfig (durations, fps, size, …)
├── application/
│   ├── ports.py            # Protocols: BasemapProvider, FrameRenderer, Encoder, LogoLoader
│   ├── use_cases/
│   │   ├── load_track.py
│   │   ├── render_animation.py
│   │   └── export_video.py
│   └── errors.py
├── adapters/
│   ├── basemaps/
│   │   ├── tiles.py        # contextily-based
│   │   ├── tiff.py         # rioxarray / rasterio
│   │   ├── none.py         # blank background
│   │   └── hillshade.py    # DEM-based (v2)
│   ├── renderers/
│   │   └── matplotlib_renderer.py
│   ├── encoders/
│   │   └── ffmpeg_encoder.py
│   ├── logos/
│   │   └── registry.py     # reads /logos/registry.yaml
│   ├── cli/
│   │   └── main.py         # click-based
│   └── gui/                # PyQt (v2, stub first)
│       └── main.py
├── config/
│   ├── defaults.py         # CONFIG dict, STYLES, SIZES, LOGO_SPECS
│   └── settings.py         # loads env, ~/.config/gpx-animate.toml
└── __init__.py
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

[tool.ruff.lint]
select = ["E","W","F","I","UP","PTH","B","C4","SIM","RET","PL","N"]
ignore = ["E501","PLR0913","PLR2004"]

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
        entry: uv run vulture src --min-confidence 80
        language: system
        pass_filenames: false
        always_run: true
      - id: pytest
        name: pytest
        entry: uv run pytest
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
- **Never mutate** the defaults dict — copy per run.
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
- `--margin 0.15` (default) — fractional padding around track bbox.
- `--bounds min_lon,min_lat,max_lon,max_lat` — overrides margin.
- Both are part of `RenderConfig`.
- Tests: bounds parsing, margin math, invalid bounds rejected.

### US-8 — PyQt GUI (v2)
**As a** user, **I want** a small GUI to pick a GPX, style, colors, logos, and
hit "Render" **so that** I don't have to remember CLI flags.

**Acceptance criteria:**
- `uv run gpx-animate-gui` launches.
- Widgets: file picker, style dropdown, duration/hold spinboxes, size dropdown,
  color pickers, logo pickers, output dir, Render button, log pane.
- Uses the **same** `application/` use cases as the CLI. No duplicated logic.
- Tests: at minimum, headless smoke test with `pytest-qt` that constructs the
  window with a fake renderer and asserts it calls the use case with the right args.

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

**Acceptance criteria:**
- `--gif` is opt-in; the MP4 is always produced. Default output path is
  `<out_stem>.gif` next to the MP4.
- Implemented as a second `Encoder` adapter (`adapters/encoders/gif_encoder.py`) —
  no new port, no duplicated frame logic.
- Encoded from the same PNG frames as the MP4, and before the temp dir is cleaned
  up: MP4 first, GIF second.
- `--gif-fps` (default `15.0`) samples every Nth rendered frame; a value greater
  than `fps` is rejected with a clear error.
- `--gif-loop` (default `0`, i.e. loop forever) sets the loop count.
- Frames are quantized to an adaptive 256-color palette. No audio, no alpha
  animation. GIFs are expected to be far larger than the MP4 — CRF-style knobs
  do not apply.
- Missing Pillow → clear error, non-zero exit, checked before rendering starts.
- Tests: frame count and sampling, loop value, palette mode, `--gif` absent writes
  no file, invalid `--gif-fps` rejected.

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
    gif: bool
    gif_fps: float
    gif_loop: int
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
  --gif [PATH]              Also write an animated GIF (default: <out_stem>.gif)
  --gif-fps FLOAT           GIF frame rate, must be <= fps [default: 15.0]
  --gif-loop INTEGER        GIF loop count, 0 = forever [default: 0]
  --log-level [DEBUG|INFO|WARNING|ERROR]
  --help
```

---

## 10. Milestones (suggested order for an agent)

1. **M0 — Tooling**: uv, ruff, ty, vulture, pre-commit, CI. Separate commit.
2. **M1 — Tests first**: pytest scaffolding, tests for the current monolith.
3. **M2 — Hexagonal refactor**: domain → application → adapters. Tests still green.
4. **M3 — Timestamped outputs** (US-4).
5. **M4 — Basemap abstraction** (US-6) + `--tiff` + `--style none`.
6. **M5 — Logo system** (US-5).
7. **M6 — Boundary control** (US-7).
8. **M7 — SPECS.md + AGENTS.md polish** (US-9).
9. **M8 — PyQt GUI** (US-8).
10. **M9 — Hillshade / 3D TIFF** (future, separate spec).
11. **M10 — GIF export** (US-10). Independent of the other milestones; can land
    any time after M2, since it only needs the `Encoder` port.

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

- Do we want a `gpx-animate.toml` project file, or rely purely on CLI + user config?
- Should the GUI support batch rendering (folder of GPX → folder of MP4)?
- For hillshade, which DEM source do we standardize on (Copernicus GLO-30, SRTM, IGN)?
- Should the "moving logo" have per-vertex rotation (e.g. car pointing along bearing)?
- Do we want a preview still (first + last frame) saved alongside the MP4?
