# AGENTS.md

Read `SPECS.md` first — it is the project mandate (architecture, tooling,
milestones, definition of done). This file records the **actual** current state,
which diverges from the spec in ways that matter.

## Current state

The repo is a **single-file script**, not the package the spec describes.

- `gpx_animate.py` (~430 lines) is the whole program: `CONFIG`, `STYLES`, `SIZES`,
  GPX parsing, geometry, matplotlib frame rendering, ffmpeg encode, argparse CLI.
  There is no `src/`, no package, no console entry points.
- `pyproject.toml`: project name is `gpx-stuff` (README/SPECS say `gpx-animate`).
  No `[tool.ruff]`, no dev deps, no `[build-system]`. The script imports `numpy`
  and `requests` without declaring them (they arrive transitively via
  matplotlib/contextily) — declare any new direct import here.
- **No tests, no linter, no type checker, no pre-commit, no CI.** ruff, ty,
  vulture, and pytest exist only as spec text (SPECS §4). Don't run or cite them;
  they will fail with "command not found". SPECS §4.7 makes bootstrapping them
  (as a separate `chore:` commit) step one.
- `data/` holds the sample GPX **and its committed reference MP4**. The default
  output name for that GPX is that same MP4, so a run without `--out` overwrites a
  tracked file — smoke-test with `--out /tmp/...`.
- `ffmpeg` must be on `PATH` (system dep, checked in `frames_to_video`).
- Basemap tiles are downloaded at render time; renders need network access.

## Commands

```bash
uv sync                                          # install deps
uv run gpx_animate.py trip.gpx                   # -> trip.mp4 next to the GPX
uv run gpx_animate.py trip.gpx --style osm --size 9:16 --out /tmp/x.mp4
```

Fast smoke test (seconds instead of a full render):

```bash
uv run gpx_animate.py trip.gpx --duration 0.2 --fps 5 --out /tmp/x.mp4
```

No test / lint / typecheck command exists yet. Until tooling lands, the only
verification is running the script end to end on a real GPX.

## Gotchas in gpx_animate.py

- `matplotlib.use("Agg")` must stay before `import matplotlib.pyplot`; the import
  order at the top of the file is load-bearing.
- `STYLES` is built at **import time**, and the Carto entries are silently dropped
  when `CARTO_API_KEY` is unset. Without that env var `--style` accepts only
  `osm|topo|satellite`, so README's `positron|voyager|dark` are unavailable and
  any `STYLES` change can't be verified locally without a key.
- `CONFIG["style"]` is `topo`; README §4 claims the default is `positron`. Trust
  the code.
- `CONFIG` is copied per run (`cfg = dict(CONFIG)`) and never mutated — keep it
  that way; precedence is `CONFIG` < CLI flags.
- A new CLI flag does nothing until its dest name is added to the whitelist tuple
  in `main()` (gpx_animate.py:390). `bg_color`, track/marker/HUD/title colors,
  `font`, `dpi`, and `zoom_padding` are CONFIG-only — no flags exist for them.
- Frame count is `int(duration*fps) + int(hold*fps)`; the truncation means the clip
  can come out shorter than `duration + hold`. Hold frames just reuse `t=1.0`.
- `requests.utils.default_headers()["User-Agent"]` is mutated at import to satisfy
  the OSM tile servers' usage policy. Don't drop it or tile fetches get blocked.
- Frames are written to a `tempfile.TemporaryDirectory()` and deleted after
  encoding; there is no `--keep-frames`, so frame debugging means re-rendering.
- Progress messages go to stdout via `print()` while ffmpeg logs to stderr, so
  piped/redirected output appears out of order (stdout is block-buffered).

## Docs that disagree with the code

- README §7 "Single track only. Only the first track/segment is used" is false:
  `load_track` flattens **all** tracks and segments into one polyline.
- README §1 advertises waypoint input; `load_track` reads tracks, then falls back
  to routes, and never touches `gpx.waypoints`.
- SPECS §3 package layout, §5 config layering (toml files + `GPX_ANIMATE_*` env),
  US-4 timestamped outputs, US-5 logo registry, US-8 PyQt GUI, US-10 GIF export:
  **not implemented**. Don't write code or docs as if they exist.

## Conventions (SPECS §6 — binding)

- Any new function comes with tests. No exceptions.
- Domain code may not import matplotlib, contextily, requests, PyQt, or ffmpeg;
  application layer talks to adapters only through `application/ports.py` protocols.
- Google-style docstrings on public functions; no magic numbers outside `config/`.
- Logging in library code; a logger adapter for the CLI.
- Keep commit prefixes separated: `chore:` / `test:` / `refactor:` / `feat:`.
  Never mix `refactor` and `feat` in one commit.
- Update `SPECS.md` when scope changes; don't silently diverge.
