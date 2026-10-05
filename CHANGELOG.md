# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
Housekeeping rule: every user-visible change updates this file in the same
commit. At a release, rename "Unreleased" to "<version> - <YYYY-MM-DD>", add a
  compare link below, and open a GitHub Release from that section.
Compare links are added at release time. The first release has no v0.0.0 tag to
  compare against, so v0.1.0 links to its own tag page rather than a compare URL
  that would 404.
See AGENTS.md -> Versioning & releases.
-->

## [Unreleased]

Nothing yet.

## [0.1.1] - 2026-10-05

One bug fix and one internal move. No flag, config key or output byte changes.

### Fixed

- **Chart videos could silently contain frames from earlier renders.** Chart
  frames were written to a fixed `/tmp/chart_frames` rather than inside the
  temporary directory, so they were never cleaned up. Because ffmpeg's image2
  demuxer reads `frame_%05d.png` sequentially until a frame is missing, leftovers
  from a longer previous render were absorbed into the next chart video — a
  three-frame chart could come out as twenty-two frames, most of them stale PNGs
  from an earlier run.

  Both frame sets now live as subdirectories of one `TemporaryDirectory`, so
  cleanup is automatic and two concurrent renders cannot share a path. This
  changes the bytes on disk for `--chart-video`: frame counts are now correct
  rather than correct-plus-leftovers. Map renders are unaffected.

### Notes

- The composition root moved out of the CLI adapter into
  `adapters/pipeline.py`, which is where a second front end will call it from.
  A behaviour baseline recorded before the move matches afterwards, frame for
  frame; the only difference across the sample renders is the chart frame count
  the fix above corrects.

## [0.1.0] - 2026-10-04

First release. There is no PyPI package — install from the GitHub tag:

```
uvx --from git+https://github.com/enarroied/gpx_animate gpx-animate trip.gpx
```

Everything below accumulated since the project began, so this section covers the
whole feature set rather than a delta.

- **Added GIF export.** `--gif` writes a `.gif` beside the MP4 from the frames
  the video already used, so there is no second render. `--gif-size`,
  `--gif-fps`, `--gif-colors`, `--gif-dither` and `--gif-loop` control it, all
  settable in config files and the environment as `gif.*` keys. Behind a new
  `GifEncoder` port; `PillowGifEncoder` is the adapter and `pillow` is now a
  declared dependency rather than arriving transitively. A missing Pillow is
  reported before the render starts.
- **Added the elevation chart.** `--profile` draws it over the map at
  `top`/`bottom` strips or any of four corners, sized by `--profile-width` and
  `--profile-height`; `--chart-video` also writes it as `<stem>-chart<suffix>`.
  Axes stay fixed to the whole track with a cursor tracking progress, and both
  videos share one progress helper so they stay frame-for-frame alignable.
  Shared drawing code lives in `elevation_chart.py`, used by both the overlay
  and a standalone `ProfileRenderer`.
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
- New: `--tiff <file>` draws a GeoTIFF you supply instead of tiles, so a render needs no
  tile server. It is reprojected to the render's projection if needed, and it must overlap
  the area being drawn or you get an error rather than an empty frame. `--tiff` wins over
  `--style`. New: `--style none` draws the track on the background colour with no map at
  all, and needs no network either. `tiff` and `style` are also settable in config files
  and the environment. Tile output is unchanged, including the on-map credit line.
- New: invalid `--size`, `--fps`, `--duration`, `--hold`, `--dpi`
  or `--margin` values are rejected up front with a message and exit code 1.
- **Behaviour change:** output now defaults to
  `./output/<gpx_stem>__<YYYYMMDD-HHMMSS>.mp4`, created on demand, instead of overwriting
  `<gpx_stem>.mp4` next to the GPX. An explicit `--out` is still honoured but is suffixed
  `__2`, `__3`, … when it already exists, so a render can no longer destroy an earlier
  one. New `--force` restores the overwrite.
- Config now has the four layers `SPECS.md` §5 asks for, below the CLI flags: the shipped
  defaults, `~/.config/gpx-animate/config.toml`, a project-local `gpx-animate.toml`, and
  `GPX_ANIMATE_*` environment variables. Every key is settable in all of them, including
  `output_dir`, `dpi` and the `appearance.*` colours, which have no flags. An unknown key
  in a file or a stray `GPX_ANIMATE_*` variable is reported at startup with the list of
  valid keys instead of being ignored.
- New: `--bounds min_lon,min_lat,max_lon,max_lat` pins the view to a fixed
  window in degrees, overriding `--margin` and the default track-bound padding.
  Invalid corners (reversed edges, or longitudes/latitudes outside the spheroid)
  are rejected up front with exit code 1. `bounds` is also settable in config
  files and the environment.
- New: `--logo-start`, `--logo-end` and `--logo-marker` place a PNG at the trip's start
  point, end point and moving head. Each source is a path to an image or a name from the
  logo registry (default `./logos/registry.yaml`, overridable with `--logo-registry`).
  Registry entries may set an anchor and a default size; anchors are "side on x / side on
  y" (`left|center|right` × `above|center|below`). **The corner `--logo` and
  `--logo-position` flags are gone**, replaced by the three point-anchored flags; the same
  three fields replace `logo` / `logo_position` in config files and the environment.
- New: `--logo-size <px>` overrides the width of every logo placement in one render
  (registry sizes describe a logo, the flag describes a render). `logo_size_px` is settable
  in config files and the environment too.
- New: `--logo-plate-padding <frac>` draws a rounded white plate behind every visible logo
  so it reads over a busy basemap, and sets the plate's padding. **Default `0.0` = no
  plate**, so an out-of-the-box render shows exactly the logo image; raise it to opt in. A
  fully transparent image still draws nothing — otherwise it would print a blank plate.
- **Behaviour change:** Default logo size increased to 96px (was 48px). Bare-path logos and
  registry defaults without explicit size use the larger default.
- **Behaviour change:** When logos are used, frames are saved with transparent background
  (alpha channel) so the video background is transparent in outputs that support it.
- Specified in `SPECS.md` but still not implemented: the PyQt GUI (US-8).

[0.1.1]: https://github.com/enarroied/gpx_animate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/enarroied/gpx_animate/releases/tag/v0.1.0
