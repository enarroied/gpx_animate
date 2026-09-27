"""Encode rendered frames into a video file."""

from __future__ import annotations

import logging
from pathlib import Path

from gpx_animate.application.ports import Encoder
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig


logger = logging.getLogger(__name__)


def export_video(
    config: RenderConfig,
    frames: RenderResult,
    encoder: Encoder,
) -> Path:
    """Encode a render result to ``config.out``.

    Args:
        config: Supplies the frame rate and the destination path.
        frames: The frames to encode.
        encoder: The port implementation that runs the encoder.

    Returns:
        The path that was written.

    Raises:
        ValueError: If the config has no output path set.
    """
    if config.out is None:
        raise ValueError("config.out must be set before encoding")

    out_path = Path(config.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Encoding %d frames to %s", frames.frame_count, out_path)
    encoder.encode(frames.frame_dir, config.fps, out_path)
    logger.info("Wrote %s", out_path)
    return out_path
