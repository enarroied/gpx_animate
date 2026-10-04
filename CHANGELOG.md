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

- **Added GIF export.** `--gif` writes a `.gif` beside the MP4 from the frames
  the video already used, so there is no second render. `--gif-size`,
  `--gif-fps`, `--gif-colors`, `--gif-dither` and `--gif-loop` control it, all
  settable in config files and the environment as `gif.*` keys. Behind a new
  `GifEncoder` port; `PillowGifEncoder` is the adapter and `pillow` is now a
  declared dependency rather than arriving transitively. A missing Pillow is
  reported before the render starts.
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
  (registry sizes describe a logo, the flag describes a render), and every visible logo now
  sits on a rounded white backplate so it reads over a busy basemap. A fully transparent
  image still draws nothing. `logo_size_px` is settable in config files and the
  environment too.
- New: `--logo-plate-padding` controls logo backplate padding (default `0.0` = no plate).
  When padding > 0, visible logos sit on a rounded white backplate.
- **Behaviour change:** Default logo size increased to 96px (was 48px). Bare-path logos and
  registry defaults without explicit size use the larger default.
- **Behaviour change:** When logos are used, frames are saved with transparent background
  (alpha channel) so the video background is transparent in outputs that support it.
- Specified in `SPECS.md` but not implemented: PyQt GUI (US-8), GIF export (US-10).
