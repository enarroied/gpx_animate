"""Encode rendered frames into a video file."""

from __future__ import annotations

import logging
from pathlib import Path

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
) -> Path:
    """Encode a render result to ``config.out``, and the GIF beside it.

    Two outputs come out of one render, in order: the video itself, then the
    GIF. The video goes first because it is the deliverable and the one every
    caller wants.

    Args:
        config: Supplies the frame rate and the destination path.
        frames: The frames to encode.
        encoder: The port implementation that runs the video encoder.
        gif_encoder: Optional port implementation that writes a GIF. Required
            only when ``config.gif.enabled`` is set; the CLI supplies it and is
            also where the Pillow availability check happens, so this layer
            never imports an adapter.

    Returns:
        The path that was written: ``config.out``.

    Raises:
        ValueError: If the config has no output path set.
        GifEncodeError: If ``config.gif.enabled`` but no encoder was provided.
    """
    if config.out is None:
        raise ValueError("config.out must be set before encoding")

    out_path = Path(config.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Encoding %d frames to %s", frames.frame_count, out_path)
    encoder.encode(frames.frame_dir, config.fps, out_path)
    logger.info("Wrote %s", out_path)

    if config.gif.enabled:
        if gif_encoder is None:
            raise GifEncodeError("no GIF encoder was provided for --gif")
        gif_path = out_path.with_name(out_path.stem + ".gif")
        logger.info("Encoding a GIF to %s", gif_path)
        gif_encoder.encode(frames.frame_dir, config.gif, config.fps, gif_path)
        logger.info("Wrote %s", gif_path)

    return out_path
