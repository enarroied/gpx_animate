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

- Single-file script (`gpx_animate.py`) run via `uv run gpx_animate.py <trip.gpx>`.
  Not an installable package yet, so there is no `gpx-animate` console entry point.
- Renders a GPX track to an H.264 MP4: matplotlib frames piped to ffmpeg.
- `--style` accepts `osm`, `topo`, and `satellite`. The Carto styles (`positron`,
  `voyager`, `dark`) are dropped at import time unless `CARTO_API_KEY` is set.
- Branding (colors, fonts, dpi, `zoom_padding`) is `CONFIG`-only — no CLI flags yet.
- Specified in `SPECS.md` but not implemented: timestamped outputs (US-4), logo
  registry (US-5), boundary flags (US-7), PyQt GUI (US-8), GIF export (US-10).
