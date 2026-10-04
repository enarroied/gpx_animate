"""In-memory stand-ins for the application ports.

They exist so the use cases can be tested without matplotlib, tile servers or
ffmpeg. They are also the executable definition of the ports: if a fake
satisfies a Protocol, the real adapter has the same obligation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from gpx_animate.application.ports import BasemapImage
from gpx_animate.application.ports import Logo
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.logo import DEFAULT_LOGO_ANCHOR
from gpx_animate.domain.logo import DEFAULT_LOGO_SIZE_PX
from gpx_animate.domain.render_config import GifConfig
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


class FakeRenderer:
    """A FrameRenderer that writes nothing and remembers what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[RenderConfig, Track, Path]] = []

    def render(self, config: RenderConfig, track: Track, out_dir: Path) -> RenderResult:
        """Return the frames the config implies, without drawing them.

        Args:
            config: Supplies the frame count.
            track: Recorded but unused.
            out_dir: Becomes the result's frame directory.

        Returns:
            A result whose paths are what a real renderer would have written.
        """
        self.calls.append((config, track, out_dir))
        frame_paths = tuple(
            out_dir / f"frame_{index:05d}.png" for index in range(config.n_frames)
        )
        return RenderResult(
            frame_dir=out_dir,
            frame_paths=frame_paths,
            frame_count=config.n_frames,
        )


class FakeEncoder:
    """An Encoder that records its arguments and writes a placeholder file."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, int, Path]] = []

    def encode(self, frame_dir: Path, fps: int, out_path: Path) -> None:
        """Record the call and create a stand-in for the video.

        Args:
            frame_dir: Recorded.
            fps: Recorded.
            out_path: Written to, so callers can assert it was produced.
        """
        self.calls.append((frame_dir, fps, out_path))
        out_path.write_bytes(b"fake video")


class FakeGifEncoder:
    """A GifEncoder that records its arguments and writes a placeholder file."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, GifConfig, int, Path]] = []

    def encode(
        self,
        frame_dir: Path,
        config: GifConfig,
        mp4_fps: int,
        out_path: Path,
    ) -> None:
        """Record the call and create a stand-in for the GIF.

        Args:
            frame_dir: Recorded, so a caller can prove the MP4's frames were reused.
            config: Recorded, to check the GIF settings reached the adapter.
            mp4_fps: Recorded, to check the source rate drives the sampling stride.
            out_path: Written to, so callers can assert it was produced.
        """
        self.calls.append((frame_dir, config, mp4_fps, out_path))
        out_path.write_bytes(b"fake gif")


class FakeBasemap:
    """A BasemapProvider that records the call instead of fetching tiles.

    Attributes:
        image: The array :meth:`get_image` returns. A mid-grey block, so it is
            visible against both a light and a dark background.
        attribution: Credit line to report, or ``None`` for a silent provider.
        extent: Extent to claim, or ``None`` to cover whatever was asked for.
    """

    def __init__(
        self,
        image: np.ndarray | None = None,
        attribution: str | None = None,
        extent: tuple[float, float, float, float] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.image = np.full((2, 2, 3), 128, dtype=np.uint8) if image is None else image
        self.attribution = attribution
        self.extent = extent

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str) -> BasemapImage:
        """Record that a basemap was requested and hand back a fixed image.

        Args:
            bbox: Recorded, so tests can assert which area was asked for.
            crs: Recorded, so tests can assert which projection was requested.
            zoom: Recorded.

        Returns:
            The fixed image, over :attr:`extent` or the whole of ``bbox``.
        """
        self.calls.append({"bbox": bbox, "crs": crs, "zoom": zoom})
        return BasemapImage(
            image=self.image,
            extent=self.extent or bbox.extent,
            crs=crs,
            attribution=self.attribution,
        )


class FakeLogoLoader:
    """A LogoLoader that returns a fixed logo instead of reading a file."""

    def __init__(
        self,
        image: np.ndarray | None = None,
        *,
        anchor: str = DEFAULT_LOGO_ANCHOR,
        size_px: int = DEFAULT_LOGO_SIZE_PX,
    ) -> None:
        """Set what :meth:`resolve` returns.

        Args:
            image: The image to return. Defaults to an opaque black square;
                a zeros array would be fully transparent and draw nothing.
            anchor: Anchor the returned logo carries.
            size_px: Width the returned logo carries.
        """
        self.image = np.ones((2, 2, 4)) if image is None else image
        self.anchor = anchor
        self.size_px = size_px
        self.calls: list[str] = []

    def resolve(self, source: str) -> Logo:
        """Return the fixed logo.

        Args:
            source: Recorded, so tests can assert which logo was asked for.
        """
        self.calls.append(source)
        return Logo(
            image=self.image, anchor=self.anchor, size_px=self.size_px, source=source
        )
