# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
Housekeeping rule: every user-visible change updates this file in the same
commit. At a release, rename "Unreleased" to "<version> - <YYYY-MM-DD>", add a
  compare link below, and open a GitHub Release from that section. Compare links
  are added at release time; there are no tags yet.
See AGENTS.md -> Versioning & releases.
-->

## [Unreleased]

Nothing has been released yet. Current state of the project:

- Installed package (`gpx_animate`) with a `gpx-animate` console entry point:
  `uv run gpx-animate <trip.gpx>`. The single-file script is gone; rendering output
  is unchanged, frame for frame.
- Renders a GPX track to an H.264 MP4: matplotlib frames piped to ffmpeg.
- Internals are now a hexagonal package (`domain` / `application` / `adapters` /
  `config`) with ports-and-protocols seams. This is invisible to users.
- `--style` accepts `osm`, `topo`, and `satellite`. The Carto styles (`positron`,
  `voyager`, `dark`) are dropped at import time unless `CARTO_API_KEY` is set.
- New: `--margin` (axes margin) and `--log-level` (`debug`/`info`/`warning`/`error`);
  library code logs through `logging` instead of `print()`.
- New: invalid `--size`, `--logo-position`, `--fps`, `--duration`, `--hold`, `--dpi`
  or `--margin` values are rejected up front with a message and exit code 1.
- Branding (colors, fonts, dpi) is still `Style`/`RenderConfig`-only — no CLI flags yet.
- Specified in `SPECS.md` but not implemented: timestamped outputs (US-4), logo
  registry (US-5), boundary flags (US-7), PyQt GUI (US-8), GIF export (US-10).
