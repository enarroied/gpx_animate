"""Run the render use case against a frame renderer."""

from __future__ import annotations

import logging
from pathlib import Path

from gpx_animate.application.ports import FrameRenderer
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)


def render_animation(
    config: RenderConfig,
    track: Track,
    out_dir: Path,
    renderer: FrameRenderer,
) -> RenderResult:
    """Render the animation's frames into ``out_dir``.

    The frame count is decided by :class:`RenderConfig`, not by the renderer, so
    this use case can report it without inspecting what came back.

    Args:
        config: Validated render settings.
        track: The track to animate.
        out_dir: Directory for the frames. The caller owns its lifetime, which
            is why the temporary directory lives in the CLI adapter.
        renderer: The port implementation that does the drawing.

    Returns:
        The frames that were written.
    """
    logger.info(
        "Rendering %d frames (%.2fs draw + %.2fs hold @ %dfps)",
        config.n_frames,
        config.duration,
        config.hold,
        config.fps,
    )
    result = renderer.render(config, track, out_dir)
    logger.info("Rendered %d frames to %s", result.frame_count, out_dir)
    return result
