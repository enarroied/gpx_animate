"""The interfaces the application layer needs from the outside world.

Every third-party dependency the pipeline touches — tile servers, matplotlib,
ffmpeg, image files — is reached through one of these protocols. That is what
lets the GUI in M8 be a second adapter over the same use cases, and what lets
the tests drive the use cases with fakes instead of network and subprocesses.

The annotations deliberately avoid naming any framework. ``BasemapProvider`` in
particular takes an opaque ``axes`` because only the matplotlib adapter knows
what a matplotlib ``Axes`` is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable

import numpy as np

from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


@dataclass(frozen=True)
class RenderResult:
    """The frames a render produced, and where they are.

    Args:
        frame_dir: Directory the frames were written to.
        frame_paths: The frames, in order, zero-padded by the renderer.
        frame_count: Total number of frames, draw plus hold.
    """

    frame_dir: Path
    frame_paths: tuple[Path, ...]
    frame_count: int


@runtime_checkable
class BasemapProvider(Protocol):
    """Draws the map underneath the track."""

    def add_basemap(self, axes: Any, **options: Any) -> None:
        """Add the basemap to ``axes``, a matplotlib ``Axes``.

        Args:
            axes: The axes to draw on. Typed as ``Any`` on purpose: the
                application layer must not import matplotlib.
            **options: Renderer-supplied hints, such as ``crs``.
        """


@runtime_checkable
class FrameRenderer(Protocol):
    """Turns a track into image frames on disk."""

    def render(self, config: RenderConfig, track: Track, out_dir: Path) -> RenderResult:
        """Render every frame of the animation.

        Args:
            config: Validated render settings.
            track: The track to draw.
            out_dir: Directory to write frames into. Created if missing.

        Returns:
            The frames that were written.
        """


@runtime_checkable
class Encoder(Protocol):
    """Turns a directory of frames into a video file."""

    def encode(self, frame_dir: Path, fps: int, out_path: Path) -> None:
        """Encode the frames in ``frame_dir`` into ``out_path``.

        Args:
            frame_dir: Directory holding the numbered frames.
            fps: Frame rate to assume for the sequence.
            out_path: Destination file, overwritten if it exists.
        """


@runtime_checkable
class LogoLoader(Protocol):
    """Loads a logo image for the renderer to draw."""

    def load(self, source: str) -> np.ndarray:
        """Read a logo into an image array.

        Args:
            source: A path, or a name from the logo registry.

        Returns:
            The image as a float array, ready for ``imshow``.
        """


@runtime_checkable
class TrackLoader(Protocol):
    """Reads a track from some source format."""

    def load(self, source: Path) -> Track:
        """Load a track.

        Args:
            source: The file to read.

        Returns:
            The parsed track.

        Raises:
            NoPointsError: If the file held no points at all.
        """


def frames_are_sequential(paths: Sequence[Path]) -> bool:
    """Return whether frame paths are numbered contiguously from zero.

    Encoders glob for ``frame_%05d.png`` and stop at the first gap, so a
    numbering mistake shows up as a silently short video. Cheap to assert.

    Args:
        paths: Frame paths in the order the renderer wrote them.

    Returns:
        True if the names are ``frame_00000`` upwards with no gaps.
    """
    return [p.stem for p in paths] == [f"frame_{i:05d}" for i in range(len(paths))]
