# AGENTS.md

Read `SPECS.md` first — it is the project mandate (architecture, tooling,
milestones, definition of done). This file records the **actual** current state,
which diverges from the spec in ways that matter.

## Current state

SPECS M0–M4 are done. The code is the hexagonal package the spec describes, it is
installable, and it can be configured from files and the environment.

```
src/gpx_animate/
├── domain/         track.py (Point, Track, haversine), style.py, render_config.py, bbox.py (Bbox)
├── application/    ports.py (Protocols), errors.py, use_cases/{load_track,render_animation,export_video}.py
├── adapters/       basemaps/{tiles,none,tiff,factory}.py, renderers/matplotlib_renderer.py,
│                   encoders/ffmpeg_encoder.py, logos/registry.py, cli/main.py, gui/main.py (stub)
└── config/         defaults.py, layers.py (reading a layer), loader.py (stacking them)
```

- `pyproject.toml` has a `[build-system]` (hatchling) and
  `[project.scripts] gpx-animate`, so `uv sync` installs the project and
  `uv run gpx-animate` / `uvx --from . gpx-animate` both work. `numpy`,
  `requests`, `rasterio` and `pyyaml` are now declared dependencies rather than
  arriving transitively.
- `tests/` mirrors the package layout: `tests/domain/`, `tests/application/`,
  `tests/adapters/`, `tests/config/`, plus `tests/fakes.py` (in-memory port
  implementations) and `tests/fixtures/`. 100% statement **and**
  branch coverage, with a 90% floor in `[tool.coverage.report] fail_under`.
  378 tests: 370 offline plus 8 `integration`-marked ones.
- The `integration`-marked tests are **deselected by default** (`addopts` has
  `-m 'not integration'`) because they need ffmpeg plus the tile servers. Run
  them with `uv run pytest -m integration`; CI runs them non-blocking.
- `data/` holds **one** committed GPX, as a sample input. Its rendered video was
  removed: it was a 750 KB binary that nothing tests or reads, and eyeballing a
  render is cheaper by running the tool. A bare `uv run gpx-animate data/*.gpx`
  writes to `./output/` (gitignored); smoke tests should still pass
  `--out /tmp/...` so they leave the repo alone. A test that exercises the
  *default* destination must `monkeypatch.chdir(tmp_path)`, or it will create
  `output/` in the repo. Note `data/.gitignore` is `*` and is itself untracked,
  so anything else you drop there stays local — only the GPX is versioned.
- `ffmpeg` must be on `PATH` (system dep, checked in `FfmpegEncoder.encode`).
- Basemap tiles are downloaded at render time; renders need network access.

## Commands

```bash
uv sync                                   # install deps + the project
uv run gpx-animate trip.gpx               # -> trip.mp4 next to the GPX
uv run gpx-animate trip.gpx --style osm --size 9:16 --out /tmp/x.mp4
```

Fast smoke test (seconds instead of a full render):

```bash
uv run gpx-animate trip.gpx --duration 0.2 --fps 5 --out /tmp/x.mp4
```

Tooling (SPECS M0/M1, paths updated for M2):

```bash
uv run ruff check .            # lint          (--fix to autofix)
uv run ruff format .           # format        (--check in CI)
uv run ty check src tests      # type check
uv run vulture src tests --min-confidence 80
uv run pytest -q               # 370 tests, offline (tiles and TIFFs are faked)
uv run pytest -m integration   # needs ffmpeg + tile servers
uv run pre-commit run --all-files
```

Gate order used by CI and the Definition of Done: `ruff check` → `ruff format
--check` → `ty` → `vulture` → `pytest`. The 90% coverage floor lives in
`[tool.coverage.report] fail_under` and is applied by CI's `--cov` run, not by
the pre-commit hook.

## Versioning & releases

`pyproject.toml`'s `version` is the single source of truth. Bump it with
`uv version --bump minor|patch` — it edits the manifest and re-locks, so no
`bump2version`/`bump-my-version` needed. **GitHub Releases only, no PyPI**, so
there is no publish token to manage.

| Version | Scope | Exit criteria |
|---|---|---|
| `0.0.0` | now: M0–M4 landed, unreleased | no tags yet |
| `0.1.0` | SPECS M3–M6 + US-10 GIF | `uvx gpx-animate trip.gpx` works; ruff/ty/pytest/pre-commit green; README accurate |
| `0.2.0` | US-8 PyQt GUI | `gpx-animate-gui` launches; headless `pytest-qt` smoke test |
| `0.3.0` | M9 hillshade / 3D TIFF | separate spec, per SPECS §10 |

The GUI is its own minor bump because it is a *new adapter* over a frozen
application layer — new capability, no breaking change. M0–M2 is invisible to
users, so it stays in `[Unreleased]` rather than burning a version number on a
refactor. M3 is the first user-visible milestone: the output path moved.

Cut procedure:

```bash
uv version --bump minor              # 0.0.0 -> 0.1.0 (manifest + uv.lock)
# edit CHANGELOG.md: [Unreleased] -> [0.1.0] - <YYYY-MM-DD>, add compare link
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: release 0.1.0"
git tag -a v0.1.0 -m "0.1.0"
git push origin HEAD --follow-tags
gh release create v0.1.0 --title "0.1.0" --notes-file <changelog-section>
```

Stage the release files explicitly — `git commit -a` will sweep in unrelated
work-in-progress edits. Same reason: any user-visible change updates
`CHANGELOG.md` in the same commit.

## Gotchas in the package

- **`domain/` must stay pure.** No matplotlib, contextily, requests, PyQt, gpxpy
  or ffmpeg imports. `numpy` is fine (arithmetic, not I/O); `gpxpy` is not, which
  is why `load_track` lives in the *application* layer. The
  `tests/application/test_ports.py` conformance tests and the port annotations
  both enforce this — as of M4 the basemap port hands over a plain
  `BasemapImage` (ndarray + extent) instead of an `axes`, so it names no
  matplotlib type at all. `domain/bbox.py` may not import rasterio either: it is
  pure arithmetic, and the reading of the file lives in the adapter.
- `matplotlib.use("Agg")` must stay before `import matplotlib.pyplot` inside
  `adapters/renderers/matplotlib_renderer.py`; the two `# noqa: E402` comments
  exist for that reason. The same pattern is load-bearing in
  `tests/adapters/basemaps/test_none.py`.
- Two deliberate `ty` suppressions remain, both on runtime-built or over-narrow
  stubs: `# ty: ignore[unresolved-attribute]` on the three `cx.providers.*` lines
  in `adapters/basemaps/tiles.py` (xyzservices builds those attributes at
  runtime) and one `# ty: ignore[invalid-argument-type]` on `set_segments`
  (matplotlib's stub is too narrow for an ndarray). `ty` reports an unused
  suppression as a *warning that fails the check*, so delete them, never leave
  them stale. `N806` is exempted per-file for the renderer only (projected `X`/`Y`).
- The Carto styles (`positron`, `voyager`, `dark`) are built at **import time** in
  `adapters/basemaps/tiles.py` and dropped when `CARTO_API_KEY` is unset, so
  `--style` offers only `osm|topo|satellite` without that env var. README's
  `positron|voyager|dark` are unavailable locally, and `TILE_PROVIDERS` changes
  cannot be verified without a key.
- The basemap style default is `topo` (`config/defaults.py`); README §4 claims
  `positron`. Trust the code.
- **No flag whitelist any more.** The old `for k in (...)` tuple in `main()` that
  silently dropped unlisted flags is gone: `config_from_args` derives overrides
  from the argparse dests, so a new flag in `build_parser` is wired by
  construction. `dpi` and the `Style` fields (`bg_color`, `track_*`, `marker_*`,
  `hud_color`, `title_color`, `font`) still have no flags.
- `CONFIG` as a mutable dict is gone. Defaults are frozen dataclass fields
  (`RenderConfig`, `Style`) composed by `config/defaults.default_config()`, and
  overrides go through `dataclasses.replace`, which re-runs `__post_init__`
  validation. Precedence is still defaults < CLI flags.
- **Output resolution lives in `application/use_cases/resolve_output.py`**, not in the
  CLI, and it is deliberately side-effect free: it picks a name, it does not create the
  directory. `export_video` does the `mkdir(parents=True)`. This means an unwritable
  destination fails before the render, not after 150 frames. The CLI calls the resolver
  and then `dataclasses.replace(config, out=...)`, so `export_video` is unchanged.
- `config_from_args(args, base)` takes the layered config as `base` and only applies
  flags on top. It does **not** invent a destination any more. Do not move the
  `out` defaulting back into it.
- `--force` uses `action="store_true", default=None`. A plain `store_true` would default
  to `False`, and since `config_from_args` treats "not `None`" as "the user said so", a
  `force = true` in a config file could never win. Same trap applies to any future
  on/off flag.
- `RenderConfig` rejects `fps <= 0`, `duration <= 0`, `hold < 0`, `dpi <= 0`,
  `margin < 0`, unknown `size`, empty `logo_start`/`logo_end`/`logo_marker`, and
  a `bounds` box that fails `domain/bbox.validate_bounds` at construction, so the
  CLI turns those into exit code 1 instead of a confusing render failure.
- `--bounds` is a **string flag parsed late**, not an argparse `type=`. Parsing
  in `parse_bounds` (domain) keeps the ValueError message flowing through main's
  exit-code-1 path and lets the same coercion serve config files and the
  environment via the `COERCERS` table's `_to_bounds`. The flag arrives as text
  because config_from_args applies only flags over the layered base — the
  COERCERS do not run for flags — so `config_from_args` re-parses `bounds` by
  hand. `bounds` replaces the padded view entirely in the renderer, margin and
  the one-unit degenerate floor included.
- Frame count is `int(duration*fps) + int(hold*fps)` and the truncation is
  intentional: a sub-frame phase disappears and the clip can come out shorter
  than `duration + hold`. Hold frames reuse the final state, so they are
  pixel-identical to the last draw frame.
- Logo sources (`--logo-start|end|marker`) are a **name or a path** — a plain
  string, deliberately not `Path`, because a registry name is not a filesystem
  path. `--logo-registry` is CLI wiring only, *not* a `RenderConfig` field, so it
  is intentionally absent from the config keys and the `COERCERS` table.
  Fail-fast resolution happens in `render_animation` (before the render log
  line); the renderer resolves again for its own use. `PngLogoLoader.resolve`
  treats an existing file as winning over a same-spelled registry name, decides
  whether a miss was a path by `_looks_like_path` (separator or suffix — so a
  typo'd path gets "file does not exist", not "unknown name"), and relative
  `file:` entries are resolved against the **registry's own directory**, not the
  cwd. Registry validation is strict: unknown entry keys, blank `file:`, unknown
  anchors and non-positive `default_size_px` are all `LogoRegistryError`s.
- Logo drawing in `matplotlib_renderer.py`: images use `aspect="auto"` and
  `origin="upper"`; xlim/ylim are re-asserted after each `imshow`. Placement
  converts `size_px` through **each axis's own scale**
  (`w = size_px*units_x`, `h = size_px*aspect*units_y`) — one shared x-derived
  scale squashes logos on wide screens. The mid trip marker logo is a single
  `AxesImage` moved per frame via a closure; start/end logos are drawn once. One
  throwaway `fig.canvas.draw()` realizes the axes extent so the device-px math
  is correct after `tight_layout`.
- The User-Agent is passed **explicitly** as `headers={"User-Agent": ...}` to
  `contextily.bounds2img`. The monolith also mutated
  `requests.utils.default_headers()["User-Agent"]` at import, which never took
  effect — that call rebuilds the dict every time. There is a test pinning this.
- `TileBasemap.get_image` calls `warp_tiles` **unconditionally**, even when the
  requested CRS already matches the tiles'. That is deliberate: M2 drew through
  `contextily.add_basemap`, which always warps, so skipping the warp would shift
  the output. Don't "optimise" it away without a pixel diff against the M2
  reference in `/tmp/m2ref`.
- `TiffBasemap` reads the **whole** file into memory and has no window/crop step.
  That was scoped out of US-6; a large raster is a memory cost, not a correctness
  one. It reprojects via `calculate_default_transform` + `reproject` and returns
  `(rows, cols, bands)`, so a single-band raster is 3-D with a trailing 1.
- `Bbox` is `(min_x, min_y, max_x, max_y)` but `BasemapImage.extent` is
  matplotlib's `(min_x, max_x, min_y, max_y)`. The mix-up is silent — both are
  four floats — so the conversion is pinned by tests. Rasterio `array_bounds`
  returns `(west, south, east, north)`, a third order.
- **The CLI reads the developer's own environment and `~/.config`.** `main()` calls
  `load_config(Path.cwd())`, so `tests/adapters/cli/test_cli_main.py` has an autouse
  `hermetic_config` fixture that strips `GPX_ANIMATE_*` from `os.environ`, points
  `layers.user_config_path` at nothing, and `chdir`s to `tmp_path`. Without it the suite's
  results depend on the machine it runs on. A hand-written `gpx-animate.toml` in the repo
  root would also be picked up; that filename is gitignored.
- **Unknown config keys are errors, on purpose** — a typo like `durtaion` is reported with
  the list of valid keys, never ignored. The set of settable keys is *derived* from the
  dataclass fields (`config/layers.py:config_keys()` walks `dataclasses.fields`), so a new
  domain field becomes settable in both files and the environment with no second list to
  keep in sync. Don't hand-maintain a key list. `settable_keys()` exists because
  `appearance` is a valid TOML *table* but not a value anyone may assign: without it
  `GPX_ANIMATE_APPEARANCE=x` would replace the whole `Style` with a string and fail far
  from the cause.
- `config/loader.py` coerces by key through the `COERCERS` table; a key that is not in it
  is passed through as a string. That is why `fps = "29.97"` is an error rather than a
  silent truncation to 29.
- Frames are written to a `tempfile.TemporaryDirectory()` owned by the **CLI
  adapter** and deleted after encoding; there is no `--keep-frames`, so frame
  debugging means re-rendering. Use `tests/fakes.py` to assert on frames instead.
- Logging replaced `print()`: library code uses `logging.getLogger(__name__)` and
  the CLI configures the root logger to stdout via `configure_logging`, so
  ffmpeg's stderr no longer interleaves with the app's output.
- Malformed GPX still raises `gpxpy.gpx.GPXXMLSyntaxException` with a traceback —
  the use case does not wrap it, so behaviour is unchanged. Deliberate failures
  (`NoPointsError`, `FfmpegNotFoundError`) subclass both `GpxAnimateError` and a
  builtin, and the CLI turns those into a message plus exit code 1.

## Gotchas in the tooling

- `ruff` 0.16 also formats Python blocks **inside Markdown**, so
  `ruff format .` will rewrite the code examples in `SPECS.md`/`README.md`.
  `extend-exclude = ["*.md"]` in `pyproject.toml` is deliberate — the spec is
  hand-authored. Don't remove it, and don't "fix" spec formatting by running
  the formatter over the docs.
- `vulture` must be given explicit source paths (`vulture src tests`).
  `vulture .` walks `.venv` and reports hundreds of false positives.
- `ty`'s `unused-ignore-comment` is a warning, not silence: a suppression that
  stops being necessary fails the check. Delete stale suppressions.
- `pythonpath = ["tests"]` in `[tool.pytest.ini_options]` is only there so
  `from fakes import FakeRenderer` works at any depth without `__init__.py` files
  in the test tree. The package itself is installed by `uv sync`, so there is no
  `pythonpath = ["."]` any more — and a stray top-level `gpx_animate.py` would
  shadow the installed package, which is why the monolith had to be deleted.
- Rendering tests must use a fake basemap (`tests/fakes.py: FakeBasemap`) or
  `BlankBasemap`; a real one makes the suite download tiles. The
  `integration`-marked tests are the only ones that hit the network.
- Watch out for the default `hold=1.0` when a test asserts a frame count: at
  5 fps that silently adds 5 frames. Pass `hold=0.0` in inline `RenderConfig`s.
- The coverage floor (90%) is enforced by CI's `--cov` run, not by the pre-commit
  hook, so a local commit can dip under it. Re-check with
  `uv run pytest -q --cov` before pushing.
- `pip-audit` is a dev dependency but wired nowhere: it needs network access on
  every run, which would make pre-commit slow and CI flaky.

## Docs that disagree with the code

- README §7 "Single track only. Only the first track/segment is used" is false:
  `load_track` flattens **all** tracks and segments into one polyline.
- README §1 advertises waypoint input; `load_track` reads tracks, then falls back
  to routes, and never touches `gpx.waypoints`.
- SPECS US-8 PyQt GUI, US-10 GIF export: **not** implemented. Don't write code
  or docs as if they exist. US-5 (logo registry), US-6 (basemap abstraction)
  and US-7 (boundary control) are implemented as of M6 — `--logo-start|end|marker`
  plus `--logo-registry`, `--tiff` / `--style none`, and `--bounds`
  (`--margin` and `--bounds` are both live `RenderConfig` fields).

## Conventions (SPECS §6 — binding)

- Any new function comes with tests. No exceptions.
- Domain code may not import matplotlib, contextily, requests, PyQt, or ffmpeg;
  application layer talks to adapters only through `application/ports.py` protocols.
- Google-style docstrings on public functions; no magic numbers outside
  `config/` and the domain's named constants (`SIZE_PRESETS`, `LOGO_POSITIONS`,
  `EARTH_RADIUS_KM`).
- Logging in library code; a logger adapter for the CLI.
- Keep commit prefixes separated: `chore:` / `test:` / `refactor:` / `feat:`.
  Never mix `refactor` and `feat` in one commit.
- Update `SPECS.md` when scope changes; don't silently diverge.
