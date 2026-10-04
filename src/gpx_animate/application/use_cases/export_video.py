"""Encode rendered frames into a video file."""

from __future__ import annotations

import logging
from pathlib import Path

from gpx_animate.application.errors import ChartFramesMissingError
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.ports import Encoder
from gpx_animate.application.ports import GifEncoder
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig


logger = logging.getLogger(__name__)


def export_video(
    config: RenderConfig,
    frames: RenderResult,
    encoder: Encoder,
    gif_encoder: GifEncoder | None = None,
    chart_frames: RenderResult | None = None,
) -> Path:
    """Encode a render result to ``config.out``, then the optional siblings.

    Three outputs come out of one render, in order: the video itself, the chart
    video, then the GIF. The video goes first because it is the deliverable and
    the one every caller wants.

    Args:
        config: Supplies the frame rate and the destination path.
        frames: The frames to encode.
        encoder: The port implementation that runs the video encoder.
        gif_encoder: Optional port implementation that writes a GIF. Required
            only when ``config.gif.enabled`` is set; the CLI supplies it and is
            also where the Pillow availability check happens, so this layer
            never imports an adapter.
        chart_frames: Frames for the elevation chart's own video, when
            ``config.chart_video`` asked for one.

    Returns:
        The path that was written: ``config.out``.

    Raises:
        ValueError: If the config has no output path set.
        GifEncodeError: If ``config.gif.enabled`` but no encoder was provided.
        ChartFramesMissingError: If ``config.chart_video`` but no frames were given.
    """
    if config.out is None:
        raise ValueError("config.out must be set before encoding")

    out_path = Path(config.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Encoding %d frames to %s", frames.frame_count, out_path)
    encoder.encode(frames.frame_dir, config.fps, out_path)
    logger.info("Wrote %s", out_path)

    if config.chart_video:
        _export_chart(config, encoder, chart_frames, out_path)

    if config.gif.enabled:
        if gif_encoder is None:
            raise GifEncodeError("no GIF encoder was provided for --gif")
        gif_path = out_path.with_name(out_path.stem + ".gif")
        logger.info("Encoding a GIF to %s", gif_path)
        gif_encoder.encode(frames.frame_dir, config.gif, config.fps, gif_path)
        logger.info("Wrote %s", gif_path)

    return out_path


def _export_chart(
    config: RenderConfig,
    encoder: Encoder,
    chart_frames: RenderResult | None,
    out_path: Path,
) -> Path:
    """Write the elevation chart's own video beside the main one.

    The sibling name is derived from the video's stem rather than run through
    :func:`resolve_output`, so a main render that happened to be numbered
    (``trip-2.mp4``) does not silently consume a second number, and an existing
    chart is overwritten rather than pushed aside.
    """
    if chart_frames is None:
        raise ChartFramesMissingError(
            "config.chart_video is set but no chart frames were provided"
        )

    chart_path = out_path.with_name(out_path.stem + "-chart" + out_path.suffix)
    logger.info("Encoding %d chart frames to %s", chart_frames.frame_count, chart_path)
    encoder.encode(chart_frames.frame_dir, config.fps, chart_path)
    logger.info("Wrote %s", chart_path)
    return chart_path
