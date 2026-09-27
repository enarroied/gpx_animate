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
from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.adapters.renderers.matplotlib_renderer import MatplotlibRenderer
from gpx_animate.application.errors import GpxAnimateError
from gpx_animate.application.use_cases.export_video import export_video
from gpx_animate.application.use_cases.load_track import load_track
from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.application.use_cases.resolve_output import resolve_output_path
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
from gpx_animate.config.loader import load_config
from gpx_animate.domain.render_config import LOGO_POSITIONS
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
    parser.add_argument("--logo", type=Path, help="PNG to draw in a corner")
    parser.add_argument(
        "--logo-position",
        choices=list(LOGO_POSITIONS),
        help="which corner the logo sits in",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="logging verbosity (default: %(default)s)",
    )
    return parser


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
    overrides = {
        field: getattr(args, field)
        for field in (
            "style",
            "tiff",
            "duration",
            "hold",
            "fps",
            "size",
            "margin",
            "out",
            "force",
            "logo",
            "logo_position",
        )
        if getattr(args, field, None) is not None
    }
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

        renderer = MatplotlibRenderer(build_basemap(config), PngLogoLoader())
        encoder = FfmpegEncoder()

        with tempfile.TemporaryDirectory() as frame_dir:
            frames = render_animation(config, track, Path(frame_dir), renderer)
            out_path = export_video(config, frames, encoder)
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
