"""Encode PNG frames into an MP4 with ffmpeg."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from gpx_animate.application.errors import FfmpegNotFoundError


logger = logging.getLogger(__name__)

FRAME_GLOB = "frame_%05d.png"
"""Matches the names ``MatplotlibRenderer`` writes."""

CRF = "18"
"""Constant rate factor. Lower is better quality and a bigger file."""

YUV420P = "yuv420p"
"""Pixel format every browser and phone can play."""


def build_command(frame_dir: Path, fps: int, out_path: Path) -> list[str]:
    """Build the ffmpeg command line.

    Split out from :class:`FfmpegEncoder` so the exact flags can be asserted in
    a test without a subprocess, and so the GIF encoder in M10 can be compared
    against it.

    Args:
        frame_dir: Directory holding the numbered frames.
        fps: Frame rate to assume for the sequence.
        out_path: Destination file.

    Returns:
        The argument vector, ready for ``subprocess.run``.
    """
    return [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(Path(frame_dir) / FRAME_GLOB),
        "-c:v",
        "libx264",
        "-pix_fmt",
        YUV420P,
        "-crf",
        CRF,
        "-preset",
        "slow",
        str(out_path),
    ]


class FfmpegEncoder:
    """Encodes frames to MP4 by shelling out to ffmpeg."""

    def encode(self, frame_dir: Path, fps: int, out_path: Path) -> None:
        """Encode ``frame_dir`` into ``out_path``.

        Args:
            frame_dir: Directory holding the numbered frames.
            fps: Frame rate to assume for the sequence.
            out_path: Destination file, overwritten if it exists.

        Raises:
            FfmpegNotFoundError: If ffmpeg is not on PATH.
            subprocess.CalledProcessError: If ffmpeg exits non-zero.
        """
        if shutil.which("ffmpeg") is None:
            raise FfmpegNotFoundError("ffmpeg not found on PATH. Install it and retry.")

        command = build_command(frame_dir, fps, Path(out_path))
        logger.debug("Running %s", " ".join(command))
        subprocess.run(command, check=True)
