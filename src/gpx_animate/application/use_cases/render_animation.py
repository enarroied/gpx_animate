"""Run the render use case against a frame renderer."""

from __future__ import annotations

import logging
from pathlib import Path

from gpx_animate.application.ports import FrameRenderer
from gpx_animate.application.ports import LogoLoader
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)


def render_animation(
    config: RenderConfig,
    track: Track,
    out_dir: Path,
    renderer: FrameRenderer,
    logos: LogoLoader | None = None,
) -> RenderResult:
    """Render the animation's frames into ``out_dir``.

    The frame count is decided by :class:`RenderConfig`, not by the renderer, so
    this use case can report it without inspecting what came back.

    Args:
        config: Validated render settings.
        track: The track to animate.
        out_dir: Directory for the frames. The caller owns its lifetime, which
            is why the temporary directory lives in
            :mod:`gpx_animate.adapters.pipeline` rather than here.
        renderer: The port implementation that does the drawing.
        logos: The logo port, when the caller has one. Supplying it makes this
            use case resolve every requested logo up front, so a mistyped name
            or a missing file is reported before the first frame is drawn rather
            than after a full render's worth of tiles. The renderer resolves
            them again itself; reading a logo is cheap next to drawing one.

    Returns:
        The frames that were written.

    Raises:
        UnknownLogoError: A requested logo is neither a file nor a known name.
        LogoFileNotFoundError: A requested logo, or a file a registry entry
            points at, is missing.
        LogoUnreadableError: A requested logo exists but is not an image.
        LogoRegistryError: The registry is present but unusable.
    """
    if logos is not None:
        for source in (config.logo_start, config.logo_end, config.logo_marker):
            if source:
                logos.resolve(source)
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
