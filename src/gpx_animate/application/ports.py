"""The interfaces the application layer needs from the outside world.

Every third-party dependency the pipeline touches — tile servers, matplotlib,
ffmpeg, image files — is reached through one of these protocols. That is what
lets the GUI in M8 be a second adapter over the same use cases, and what lets
the tests drive the use cases with fakes instead of network and subprocesses.

The annotations deliberately avoid naming any framework. ``BasemapProvider`` in
particular returns a plain ``numpy`` array over a :class:`~gpx_animate.domain.bbox.Bbox`
rather than drawing onto an ``Axes``: no matplotlib type appears in a signature,
and a provider can be unit-tested without a figure, a canvas or a network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import runtime_checkable

import numpy as np

from gpx_animate.domain.bbox import Bbox
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


@dataclass(frozen=True)
class BasemapImage:
    """A raster to draw under the track, and the area it covers.

    The image is ``(rows, cols, bands)`` with band count 3 (RGB) or 4 (RGBA),
    ``uint8`` in ``0..255``, except the do-nothing provider which returns a
    transparent float block in ``0..1`` because that is what matplotlib wants
    for RGBA.

    Row 0 is the *northern* edge, as the map and GeoTIFF readers both produce,
    which is what matplotlib's default ``origin="upper"`` expects. A provider
    returning a south-up raster has to flip it before getting here, or the map
    comes out mirrored.

    Args:
        image: Pixel values.
        extent: The covered area as ``(min_x, max_x, min_y, max_y)``, the order
            matplotlib's ``imshow`` expects.
        crs: The projection ``extent`` is expressed in.
        attribution: Copyright line the provider requires be shown, if any.
            OSM's tile policy does; a local GeoTIFF does not.
    """

    image: np.ndarray
    extent: tuple[float, float, float, float]
    crs: str
    attribution: str | None = None

    @property
    def bbox(self) -> Bbox:
        """The covered area as a :class:`Bbox`."""
        min_x, max_x, min_y, max_y = self.extent
        return Bbox(min_x, min_y, max_x, max_y)


@runtime_checkable
class BasemapProvider(Protocol):
    """Supplies the map image drawn underneath the track."""

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str) -> BasemapImage:
        """Fetch the raster covering ``bbox``.

        Args:
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection, e.g. ``EPSG:3857``. A provider that cannot
                reproject says so rather than returning a wrongly-placed image.
            zoom: Tile zoom level, or ``"auto"`` to let the provider choose.
                Ignored by providers that do not use tiles.

        Returns:
            The raster and the extent it actually covers.
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
