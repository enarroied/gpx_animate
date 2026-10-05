"""The composition root: the one place that knows how to wire a render together.

Hexagonal architecture says the application layer depends on ports and adapters
depend on the application. That leaves one job unassigned: something has to
choose the *concrete* adapters and hand them to the use cases. Before this
module that job belonged to ``adapters/cli/main.py``, which quietly made the CLI
the only front end that could render anything -- and a GUI would have had to
copy those fifty lines rather than call them. Copying them would have produced
two wirings that pass every test while drifting apart, which is the same failure
mode the elevation chart already guards against by sharing one
``revealed_point_count`` function object.

So the wiring lives here instead, and both front ends call it. What stays in
each front end is only what is genuinely specific to it: ``cli/main.py`` owns
argparse, logging setup, exit codes and flag-to-config coercion; ``gui/main.py``
owns widgets and a Qt event loop. Neither owns the render.

Why this lives in ``adapters/`` and not ``application/``: this module constructs
:class:`~gpx_animate.adapters.renderers.matplotlib_renderer.MatplotlibRenderer`
and friends, so it names concrete adapter classes. The application layer must
not know those exist.
"""

from __future__ import annotations

import dataclasses
import logging
import tempfile
from pathlib import Path

from gpx_animate.adapters.basemaps.factory import build_basemap
from gpx_animate.adapters.encoders.ffmpeg_encoder import FfmpegEncoder
from gpx_animate.adapters.encoders.gif_encoder import PillowGifEncoder
from gpx_animate.adapters.encoders.gif_encoder import require_pillow
from gpx_animate.adapters.logos.registry import LogoRegistry
from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.adapters.paths import resolve_output_dir
from gpx_animate.adapters.renderers.matplotlib_renderer import MatplotlibRenderer
from gpx_animate.adapters.renderers.profile_renderer import ProfileRenderer
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.ports import GifEncoder
from gpx_animate.application.use_cases.export_video import export_video
from gpx_animate.application.use_cases.load_track import load_track
from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.application.use_cases.resolve_output import resolve_output_path
from gpx_animate.domain.render_config import RenderConfig


logger = logging.getLogger(__name__)


def build_gif_encoder(config: RenderConfig) -> GifEncoder | None:
    """Build the GIF encoder a config asks for, checking it can work first.

    Both checks here are deliberately *before* the render rather than left to the
    encoder. A missing Pillow or an impossible frame rate is one line of output
    when it is caught now; discovering it after the frames are written wastes a
    whole pass of tile downloads to learn nothing.

    Args:
        config: Supplies ``gif.enabled`` and the frame rates to compare.

    Returns:
        The encoder to hand to :func:`export_video`, or ``None`` when the config
        does not ask for a GIF. ``None`` means "no GIF", not "GIF broken".

    Raises:
        GifEncodeError: Pillow is not importable, or the GIF frame rate exceeds
            the video's, which would mean inventing frames.
    """
    if not config.gif.enabled:
        return None

    require_pillow()
    if config.gif.fps > config.fps:
        # Frames cannot be invented. Checked here rather than left to the
        # encoder, which would only find out after rendering everything.
        raise GifEncodeError(
            f"gif fps ({config.gif.fps}) cannot be greater than "
            f"the video fps ({config.fps}); frames cannot be invented"
        )
    return PillowGifEncoder()


def render_to_video(
    config: RenderConfig,
    gpx: Path,
    *,
    logo_registry: Path | None = None,
) -> Path:
    """Render one track and write every output it asks for.

    This is the whole render, in the order that costs the least when something
    is wrong: an unwritable destination fails before a single tile is fetched, a
    missing Pillow fails before the frames are drawn, and a mistyped logo fails
    before the first frame. Only then does any real work start.

    Args:
        config: Validated render settings. ``config.out`` may be ``None``, in
            which case the destination is resolved here from ``config.output_dir``
            and the gpx stem, so a front end cannot forget to.
        gpx: The track to render.
        logo_registry: Registry file for ``--logo-*`` names. Defaults to
            :data:`~gpx_animate.adapters.logos.registry.DEFAULT_REGISTRY_PATH`.
            A parameter rather than a :class:`RenderConfig` field because
            ``--logo-registry`` is front-end wiring, not a render setting; both
            front ends pass it, so neither is privileged.

    Returns:
        The path the video was written to.

    Raises:
        GifEncodeError: The config asks for a GIF that cannot be encoded.
        NoPointsError: The GPX has no track points.
        ChartFramesMissingError: ``config.chart_video`` is set but no chart
            frames were produced.
        OSError: Something on disk refused to cooperate.
    """
    # Resolve the destination before rendering, so an unwritable path costs
    # nothing instead of a full render's worth of tiles and frames.
    # A relative output_dir is rebased first, which is a no-op unless the
    # program is frozen -- see adapters.paths for why the two cases differ.
    located = dataclasses.replace(
        config, output_dir=resolve_output_dir(config.output_dir)
    )
    config = dataclasses.replace(config, out=resolve_output_path(located, gpx))

    track = load_track(gpx)
    logger.info(
        "%d points, route %r, %.1f km, %d m of climbing",
        len(track.points),
        track.name,
        track.total_distance_km(),
        track.elevation_gain_m(),
    )

    # Fail before the render, not after: a missing Pillow is a one-line error,
    # whereas discovering it once the frames are written wastes the whole pass.
    gif_encoder = build_gif_encoder(config)

    logos = PngLogoLoader(LogoRegistry(logo_registry))
    renderer = MatplotlibRenderer(build_basemap(config), logos)
    encoder = FfmpegEncoder()

    with tempfile.TemporaryDirectory() as work_dir:
        # Both frame sets live under one temporary directory, as two
        # subdirectories rather than two sibling temporary directories. A chart
        # render used to go to a fixed /tmp/chart_frames, which leaked every
        # frame of every chart render and made two concurrent renders -- a CLI
        # run and a GUI run, say -- write into the same directory. The encoder
        # globs its own directory non-recursively, so a subdirectory cannot be
        # mistaken for extra map frames.
        frame_dir = Path(work_dir) / "frames"
        frame_dir.mkdir()
        frames = render_animation(config, track, frame_dir, renderer, logos)

        chart_frames = None
        if config.chart_video:
            chart_renderer = ProfileRenderer()
            chart_dir = Path(work_dir) / "chart"
            chart_dir.mkdir()
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

    logger.info("Done: %s", out_path)
    return out_path
