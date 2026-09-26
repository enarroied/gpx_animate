# AGENTS.md

Read `SPECS.md` first — it is the project mandate (architecture, tooling,
milestones, definition of done). This file records the **actual** current state,
which diverges from the spec in ways that matter.

## Current state

The repo is a **single-file script**, not the package the spec describes.

- `gpx_animate.py` (~430 lines) is the whole program: `CONFIG`, `STYLES`, `SIZES`,
  GPX parsing, geometry, matplotlib frame rendering, ffmpeg encode, argparse CLI.
  There is no `src/`, no package, no console entry points.
- `pyproject.toml`: no `[tool.ruff]`, no dev deps, no `[build-system]` — the
  project is *virtual* (`uv.lock` marks it `source = { virtual = "." }`), so
  `uv sync` does not install it and there is no `gpx-animate` entry point. The
  script imports `numpy` and `requests` without declaring them (they arrive
  transitively via matplotlib/contextily) — declare any new direct import here.
  Don't add `[build-system]` before the `src/` package exists; it would make
  `uv sync` try to install a project with nothing importable.
- **Tooling is installed** (SPECS M0): ruff, ty, vulture, pytest, pytest-cov,
  pre-commit, pip-audit are dev dependencies. `uv run ruff check .`,
  `uv run ty check .`, `uv run vulture gpx_animate.py`, `uv run pre-commit run
  --all-files` all pass. **There are still no tests** — `uv run pytest` exits 5
  ("no tests collected") and both the pre-commit hook and CI tolerate that until
  M1. No `[tool.pytest.ini_options]` yet, so there is no `testpaths` or coverage gate.
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

Tooling (SPECS M0):

```bash
uv run ruff check .            # lint          (--fix to autofix)
uv run ruff format .           # format        (--check in CI)
uv run ty check .              # type check    (becomes `src tests` at M2)
uv run vulture gpx_animate.py --min-confidence 80
uv run pytest -q               # exits 5 until M1 adds the first test
uv run pre-commit run --all-files
```

Gate order used by CI and the Definition of Done: `ruff check` → `ruff format
--check` → `ty` → `vulture` → `pytest`.

## Versioning & releases

`pyproject.toml`'s `version` is the single source of truth. Bump it with
`uv version --bump minor|patch` — it edits the manifest and re-locks, so no
`bump2version`/`bump-my-version` needed. **GitHub Releases only, no PyPI**, so
there is no publish token to manage and no need for a `[build-system]` before
the `src/` package lands.

| Version | Scope | Exit criteria |
|---|---|---|
| `0.0.0` | now: unreleased single-file script | no tags yet |
| `0.1.0` | SPECS M0–M6 + US-10 GIF, packaged CLI | `uvx gpx-animate trip.gpx` works; ruff/ty/pytest/pre-commit green; README accurate |
| `0.2.0` | US-8 PyQt GUI | `gpx-animate-gui` launches; headless `pytest-qt` smoke test |
| `0.3.0` | M9 hillshade / 3D TIFF | separate spec, per SPECS §10 |

The GUI is its own minor bump because it is a *new adapter* over a frozen
application layer — new capability, no breaking change. M0–M6 is invisible to
users, so it stays in `[Unreleased]` rather than burning a version number on a
refactor.

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

## Gotchas in gpx_animate.py

- `matplotlib.use("Agg")` must stay before `import matplotlib.pyplot`; the import
  order at the top of the file is load-bearing. The three `# noqa: E402` comments
  below it exist for that reason — don't let `ruff --fix` "tidy" them away.
- Four lint/type suppressions are deliberate debt, all removed with the file at
  M2: `# ty: ignore[unresolved-attribute]` on the three `cx.providers.*` lines
  (xyzservices builds those attributes at runtime, so ty can't see them),
  `# ty: ignore[invalid-argument-type]` on `lc.set_segments` (matplotlib's stub
  is too narrow for an ndarray), and the `N806` per-file ignore in
  `pyproject.toml` for the geo/plot names `R`, `X`, `Y`, `W`, `H`. `ty` reports
  an unused suppression as a warning, so they must be removed, not left stale.
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

## Gotchas in the tooling

- `ruff` 0.16 also formats Python blocks **inside Markdown**, so
  `ruff format .` will rewrite the code examples in `SPECS.md`/`README.md`.
  `extend-exclude = ["*.md"]` in `pyproject.toml` is deliberate — the spec is
  hand-authored. Don't remove it, and don't "fix" spec formatting by running
  the formatter over the docs.
- `vulture` must be given explicit source paths (`vulture gpx_animate.py`).
  `vulture .` walks `.venv` and reports hundreds of false positives.
- `ty`'s `unused-ignore-comment` is a warning, not silence: a suppression that
  stops being necessary fails the check. Delete stale suppressions.
- `SPECS.md` §4.2/§4.3/§4.5 specify `src tests` paths that don't exist until M2;
  the pre-commit config and CI use the real paths with a comment saying so.
- `pytest` currently exits 5 (no tests collected). The pre-commit hook and the CI
  step both swallow that with `|| [ $? -eq 5 ]`; remove the tolerance in M1 when
  real tests land.
- `pip-audit` is a dev dependency but wired nowhere: it needs network access on
  every run, which would make pre-commit slow and CI flaky.

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
