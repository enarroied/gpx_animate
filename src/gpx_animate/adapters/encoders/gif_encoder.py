"""Encode PNG frames into an animated GIF.

Downscales the frames the MP4 is already using rather than re-rendering them: a
second render pass would cost more than the saving. The target size is honoured
exactly, cropping rather than distorting when the aspect ratios disagree.
"""

from __future__ import annotations

import logging
from pathlib import Path

from gpx_animate.application.errors import GifEncodeError
from gpx_animate.domain.render_config import GifConfig


try:
    from PIL import Image
    from PIL import ImageOps
except Exception:  # noqa: BLE001
    Image = None
    ImageOps = None

logger = logging.getLogger(__name__)

FRAME_GLOB = "frame_*.png"
"""Matches the ``frame_%05d.png`` names every renderer writes.

A glob, not the printf pattern :mod:`~gpx_animate.adapters.encoders.ffmpeg_encoder`
hands to ffmpeg: ``Path.glob`` has no ``%d``, so passing that pattern here
would silently match nothing.
"""


def pillow_available() -> bool:
    """Whether Pillow could be imported.

    Returns:
        True if :mod:`PIL` is importable, False if it is not.
    """
    return Image is not None


def require_pillow() -> None:
    """Raise :class:`GifEncodeError` if Pillow is missing.

    Call this *before* rendering, not after: SPECS US-10 asks for the missing
    dependency to be reported before a render's worth of tiles and frames have
    been spent, and by the time frames exist the cost is already paid.

    Raises:
        GifEncodeError: If Pillow is not importable.
    """
    if Image is None:
        raise GifEncodeError("Pillow is required to encode GIFs")


def frame_step(mp4_fps: int, gif_fps: int) -> int:
    """How many source frames to skip between GIF frames.

    Args:
        mp4_fps: Frame rate of the rendered frames.
        gif_fps: Frame rate asked for.

    Returns:
        The sampling stride, at least 1 so a clip never samples zero frames.
    """
    if gif_fps <= 0:
        return 1
    return max(1, round(mp4_fps / gif_fps))


def frame_delay_ms(gif_fps: int) -> int:
    """Per-frame delay in milliseconds, rounded to a whole centisecond.

    GIF stores frame delays in hundredths of a second and Pillow **truncates**
    what it is handed, so any delay that is not a multiple of 10 ms loses up to
    9 ms on the way to disk. Rounding here is what makes the stored value mean
    what we meant.

    The obvious alternative -- round to the nearest millisecond -- is wrong, and
    silently so. A 15 fps request would compute 67 ms, which truncates to 60 ms
    and plays back at 16.7 fps: eleven percent *faster* than asked for. Rounding
    to the nearest centisecond gives 70 ms, about 14.3 fps, under five percent
    slow, which is the closer error and the one that cannot read as a bug.

    Args:
        gif_fps: Frame rate asked for.

    Returns:
        The delay to hand to Pillow, in milliseconds: a positive multiple of 10.
    """
    if gif_fps <= 0:
        return 100
    return max(10, round(1000.0 / gif_fps / 10) * 10)


def _resampling():
    """Pillow's Lanczos filter, however this version spells it.

    Pillow 10 moved the constants onto ``Image.Resampling`` and dropped the
    old ``Image.ANTIALIAS`` spelling, so the location is resolved once here
    rather than guessed at each call site.
    """
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", 1)


class PillowGifEncoder:
    """Encodes frames to an animated GIF, downscaling the MP4's frames."""

    def encode(
        self, frame_dir: Path, config: GifConfig, mp4_fps: int, out_path: Path
    ) -> None:
        """Encode ``frame_dir`` into an animated GIF at ``out_path``.

        Args:
            frame_dir: Directory holding the numbered frames.
            config: Target size, palette, dither and loop settings.
            mp4_fps: Frame rate of ``frame_dir``, used to sample against.
            out_path: Destination file, overwritten if it exists.

        Raises:
            GifEncodeError: If Pillow is missing, ``frame_dir`` holds no frames,
                or ``config.fps`` is above ``mp4_fps`` (frames cannot be
                invented, so the ask is refused rather than silently honoured by
                repeating frames).
        """
        if Image is None or ImageOps is None:
            raise GifEncodeError("Pillow is required to encode GIFs")

        if mp4_fps < config.fps:
            raise GifEncodeError(
                f"GIF fps ({config.fps}) cannot be greater than source fps ({mp4_fps})"
            )

        frame_paths = sorted(Path(frame_dir).glob(FRAME_GLOB))
        if not frame_paths:
            raise GifEncodeError(f"No frames found in {frame_dir}")

        sampled = frame_paths[0 :: frame_step(mp4_fps, config.fps)]
        resampling = _resampling()
        frames = [
            ImageOps.fit(
                Image.open(path).convert("RGB"),
                (config.width, config.height),
                resampling,
            )
            for path in sampled
        ]

        frames[0].save(
            str(out_path),
            save_all=True,
            append_images=frames[1:],
            duration=frame_delay_ms(config.fps),
            loop=config.loop,
            optimize=True,
            palette=Image.Palette.ADAPTIVE,
            colors=config.colors,
            dither=Image.Dither.FLOYDSTEINBERG if config.dither else Image.Dither.NONE,
        )

        logger.info(
            "Wrote GIF: %s (%d bytes, %d frames)",
            out_path,
            out_path.stat().st_size,
            len(frames),
        )
