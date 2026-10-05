"""Encode PNG frames into an MP4 with ffmpeg."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from gpx_animate.adapters.paths import application_dir
from gpx_animate.application.errors import FfmpegNotFoundError


logger = logging.getLogger(__name__)

FFMPEG = "ffmpeg"
"""The binary name looked up on PATH."""

FRAME_GLOB = "frame_%05d.png"
"""Matches the names ``MatplotlibRenderer`` writes."""

CRF = "18"
"""Constant rate factor. Lower is better quality and a bigger file."""

YUV420P = "yuv420p"
"""Pixel format every browser and phone can play."""


def _bundled_candidates() -> list[Path]:
    """ffmpeg paths to try beside the program, most specific first.

    A build that ships ffmpeg puts it in the directory holding the executable
    (frozen builds) or beside the entry-point script (a source checkout plus a
    ``.bat``). Both the bare name and the Windows extension are tried, because
    ``ffmpeg.exe`` cannot be executed as ``ffmpeg`` on Windows.
    """
    directory = application_dir()
    return [directory / f"{FFMPEG}{suffix}" for suffix in (".exe", "")]


def find_ffmpeg() -> str | None:
    """Locate the ffmpeg binary, preferring one shipped beside the program.

    PATH is still consulted, and is the only place a system install will be
    found. The bundled copy wins so that a portable install encodes with the
    ffmpeg it was tested against instead of whatever the machine happens to
    have -- a version mismatch here shows up as a confusing encoder failure
    rather than a missing-binary error.

    Returns:
        An executable path or bare name, or ``None`` if there is no ffmpeg.
    """
    for candidate in _bundled_candidates():
        if candidate.is_file():
            logger.debug("Using bundled ffmpeg at %s", candidate)
            return str(candidate)
    return shutil.which(FFMPEG)


def build_command(
    frame_dir: Path,
    fps: int,
    out_path: Path,
    *,
    executable: str = FFMPEG,
) -> list[str]:
    """Build the ffmpeg command line.

    Split out from :class:`FfmpegEncoder` so the exact flags can be asserted in
    a test without a subprocess, and so the GIF encoder in M10 can be compared
    against it.

    Args:
        frame_dir: Directory holding the numbered frames.
        fps: Frame rate to assume for the sequence.
        out_path: Destination file.
        executable: The ffmpeg to invoke. Defaults to the bare name, which
            leaves resolution to ``PATH``.

    Returns:
        The argument vector, ready for ``subprocess.run``.
    """
    return [
        executable,
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
            FfmpegNotFoundError: If no ffmpeg can be found beside the program
                or on PATH.
            subprocess.CalledProcessError: If ffmpeg exits non-zero.
        """
        executable = find_ffmpeg()
        if executable is None:
            raise FfmpegNotFoundError(
                "ffmpeg not found next to this program or on PATH. Install it "
                "and retry, or put ffmpeg beside gpx-animate."
            )

        command = build_command(frame_dir, fps, Path(out_path), executable=executable)
        logger.debug("Running %s", " ".join(command))
        subprocess.run(command, check=True)
