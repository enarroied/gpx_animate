"""In-memory stand-ins for the application ports.

They exist so the use cases can be tested without matplotlib, tile servers or
ffmpeg. They are also the executable definition of the ports: if a fake
satisfies a Protocol, the real adapter has the same obligation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from gpx_animate.application.ports import RenderResult
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


class FakeBasemap:
    """A BasemapProvider that records the call instead of fetching tiles."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def add_basemap(self, axes: Any, **options: Any) -> None:
        """Record that a basemap was requested.

        Args:
            axes: Recorded by identity.
            **options: Recorded, so tests can assert on crs and the like.
        """
        self.calls.append({"axes": axes, **options})


class FakeLogoLoader:
    """A LogoLoader that returns a fixed array instead of reading a file."""

    def __init__(self, image: np.ndarray | None = None) -> None:
        """Set the array returned by :meth:`load`.

        Args:
            image: The image to return. Defaults to an opaque black square;
                a zeros array would be fully transparent and draw nothing.
        """
        self.image = np.ones((2, 2, 4)) if image is None else image
        self.calls: list[str] = []

    def load(self, source: str) -> np.ndarray:
        """Return the fixed image.

        Args:
            source: Recorded, so tests can assert which logo was asked for.
        """
        self.calls.append(source)
        return self.image
