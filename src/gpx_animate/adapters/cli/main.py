"""The command line adapter.

An adapter's whole job is wiring: parse arguments, build the adapters, call the
use cases, and turn errors into exit codes. No drawing, no geometry, and no
deciding what a frame looks like.

The temporary frame directory is owned here rather than in a use case, because
it is a filesystem resource the application layer should not have to know
about.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import tempfile
from pathlib import Path

from gpx_animate.adapters.basemaps.factory import build_basemap
from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.encoders.ffmpeg_encoder import FfmpegEncoder
from gpx_animate.adapters.encoders.gif_encoder import PillowGifEncoder
from gpx_animate.adapters.encoders.gif_encoder import require_pillow
from gpx_animate.adapters.logos.registry import DEFAULT_REGISTRY_PATH
from gpx_animate.adapters.logos.registry import LogoRegistry
from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.adapters.renderers.matplotlib_renderer import MatplotlibRenderer
from gpx_animate.adapters.renderers.profile_renderer import ProfileRenderer
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.errors import GpxAnimateError
from gpx_animate.application.use_cases.export_video import export_video
from gpx_animate.application.use_cases.load_track import load_track
from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.application.use_cases.resolve_output import resolve_output_path
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
from gpx_animate.config.layers import GIF_GROUP
from gpx_animate.config.layers import settable_keys
from gpx_animate.config.loader import load_config
from gpx_animate.domain.bbox import parse_bounds
from gpx_animate.domain.render_config import PROFILE_POSITIONS
from gpx_animate.domain.render_config import RenderConfig


logger = logging.getLogger(__name__)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Every flag is optional and defaults to ``None``, which is how
    :func:`config_from_args` tells "not given" apart from "given the default
    value". Passing ``CONFIG`` values straight into ``add_argument`` would make
    the two indistinguishable.

    Returns:
        The parser, without the program name.
    """
    parser = argparse.ArgumentParser(
        prog="gpx-animate",
        description="Animate a GPX file into a short MP4.",
    )
    parser.add_argument("gpx", type=Path, help="GPX file to animate")
    parser.add_argument(
        "--style",
        choices=style_choices(),
        help="basemap style; the default ships in config/defaults.py",
    )
    parser.add_argument(
        "--tiff",
        type=Path,
        help="local GeoTIFF to draw instead of downloaded tiles; wins over --style",
    )
    parser.add_argument("--duration", type=float, help="drawing duration in seconds")
    parser.add_argument("--hold", type=float, help="hold time at the end, seconds")
    parser.add_argument("--fps", type=int, help="frames per second")
    parser.add_argument("--size", choices=sorted(SIZES), help="output aspect ratio")
    parser.add_argument(
        "--margin",
        type=float,
        help="extra padding around the track, as a fraction of its extent",
    )
    parser.add_argument(
        "--bounds",
        metavar="MIN_LON,MIN_LAT,MAX_LON,MAX_LAT",
        help="fixed view in degrees; overrides --margin",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="output file; defaults to a timestamped name in output_dir",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=None,
        help="overwrite --out if it exists instead of suffixing it",
    )
    parser.add_argument(
        "--logo-start",
        metavar="NAME|PATH",
        help="logo drawn on the track's first point, still",
    )
    parser.add_argument(
        "--logo-end",
        metavar="NAME|PATH",
        help="logo drawn on the track's last point, still",
    )
    parser.add_argument(
        "--logo-marker",
        metavar="NAME|PATH",
        help="logo drawn on the head of the growing line, moving with it",
    )
    parser.add_argument(
        "--logo-size",
        type=int,
        metavar="PX",
        help="override logo width in device pixels, for every placement",
    )
    parser.add_argument(
        "--logo-plate-padding",
        type=float,
        metavar="FRAC",
        help="padding fraction for logo plate (0.0 for no plate)",
    )
    parser.add_argument(
        "--logo-registry",
        type=Path,
        metavar="PATH",
        help=f"registry mapping names to images [default: {DEFAULT_REGISTRY_PATH}]",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="logging verbosity (default: %(default)s)",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        default=None,
        help="also write a GIF",
    )
    parser.add_argument(
        "--gif-size",
        metavar="WIDTHxHEIGHT",
        help="GIF pixel box",
    )
    parser.add_argument(
        "--gif-fps",
        type=int,
        metavar="FPS",
        help="GIF frame rate",
    )
    parser.add_argument(
        "--gif-colors",
        type=int,
        metavar="COLORS",
        help="GIF palette size (64, 128, 256)",
    )
    parser.add_argument(
        "--gif-dither",
        action="store_true",
        default=None,
        help="enable dithering for GIF",
    )
    parser.add_argument(
        "--gif-loop",
        type=int,
        metavar="LOOP",
        help="GIF loop count (0 = infinite)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_POSITIONS),
        default=None,
        help="elevation chart position (default: off)",
    )
    parser.add_argument(
        "--profile-height",
        type=float,
        metavar="FRAC",
        help="chart height as fraction of frame height",
    )
    parser.add_argument(
        "--profile-width",
        type=float,
        metavar="FRAC",
        help=(
            "chart width as fraction of frame width; ignored by the "
            "full-width top and bottom strips"
        ),
    )
    parser.add_argument(
        "--chart-video",
        action="store_true",
        default=None,
        help="also write the elevation chart as its own video",
    )

    return parser


DEST_REMAP = {"logo_size": "logo_size_px"}
"""Flags whose argparse dest differs from the config field they set."""


def config_from_args(
    args: argparse.Namespace, base: RenderConfig | None = None
) -> RenderConfig:
    """Build the render config from parsed arguments.

    Precedence is the config layers then the flags, matching SPECS section 5:
    the CLI wins. ``None`` means the flag was not given, so the layer below
    survives -- which is why every flag defaults to ``None`` rather than to its
    documented value.

    Args:
        args: Parsed arguments.
        base: The config the lower layers resolved to. Defaults to the shipped
            defaults, so the function stays usable and testable on its own.

    Returns:
        The config for this run, with ``out`` still unresolved.
    """
    # Derived from the argparse dests and the config's own fields rather than a
    # hand-maintained list, so a new flag in build_parser is wired by
    # construction instead of needing a second edit here to take effect.
    settable = set(settable_keys())
    top_level = {key for key in settable if "." not in key}

    overrides: dict = {}
    gif_overrides: dict = {}
    for dest, value in vars(args).items():
        if value is None:
            # None means the flag was not given, so the layer below survives.
            continue
        if dest.startswith(f"{GIF_GROUP}_"):
            gif_overrides[dest[len(GIF_GROUP) + 1 :]] = value
        elif dest == GIF_GROUP:
            # The bare --gif flag is the config's "enabled", not a GifConfig.
            gif_overrides["enabled"] = value
        elif dest in DEST_REMAP:
            overrides[DEST_REMAP[dest]] = value
        elif dest in top_level:
            overrides[dest] = value

    if "bounds" in overrides:
        # The flag arrives as "min_lon,min_lat,max_lon,max_lat" and the domain
        # wants a box; the config-file layers coerce through the COERCERS table,
        # but flags bypass it, so the same parse happens here.
        overrides["bounds"] = parse_bounds(overrides["bounds"])

    if gif_overrides:
        overrides[GIF_GROUP] = dataclasses.replace(
            base.gif if base else default_config().gif, **gif_overrides
        )
    return dataclasses.replace(base or default_config(), **overrides)


def configure_logging(level: str) -> None:
    """Send library and CLI logs to stdout at the requested level.

    Args:
        level: One of :data:`LOG_LEVELS`.
    """
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    try:
        # Layers 1 to 4 of SPECS section 5; the flags are layer 5.
        config = config_from_args(args, load_config(Path.cwd()))
        # Resolve the destination before rendering, so an unwritable path costs
        # nothing instead of a full render's worth of tiles and frames.
        config = dataclasses.replace(config, out=resolve_output_path(config, args.gpx))
        track = load_track(args.gpx)
        logger.info(
            "%d points, route %r, %.1f km, %d m of climbing",
            len(track.points),
            track.name,
            track.total_distance_km(),
            track.elevation_gain_m(),
        )

        # Fail before the render, not after it: a missing Pillow is a one-line
        # error, whereas discovering it once the frames are written wastes the
        # whole pass.
        gif_encoder = None
        if config.gif.enabled:
            require_pillow()
            if config.gif.fps > config.fps:
                # Frames cannot be invented. Checked here rather than left to the
                # encoder, which would only find out after rendering everything.
                raise GifEncodeError(
                    f"gif fps ({config.gif.fps}) cannot be greater than "
                    f"the video fps ({config.fps}); frames cannot be invented"
                )
            gif_encoder = PillowGifEncoder()

        logos = PngLogoLoader(LogoRegistry(args.logo_registry))
        renderer = MatplotlibRenderer(build_basemap(config), logos)
        encoder = FfmpegEncoder()

        with tempfile.TemporaryDirectory() as frame_dir:
            frames = render_animation(config, track, Path(frame_dir), renderer, logos)

            chart_frames = None
            if config.chart_video:
                chart_renderer = ProfileRenderer()
                chart_dir = Path(frame_dir).parent / "chart_frames"
                chart_dir.mkdir(parents=True, exist_ok=True)
                chart_frames = render_animation(
                    config, track, chart_dir, chart_renderer, logos
                )

            out_path = export_video(
                config,
                frames,
                encoder,
                gif_encoder=gif_encoder,
                chart_frames=chart_frames,
            )
    except GpxAnimateError as error:
        # Deliberate failures get a message, not a traceback.
        logger.error("%s", error)
        return 1
    except (OSError, ValueError) as error:
        logger.error("%s", error)
        return 1

    logger.info("Done: %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
