"""Validated render settings, and the frame arithmetic derived from them.

Every knob the pipeline reads lives here as a frozen dataclass field, so a bad
value is rejected at construction rather than turning into a confusing failure
halfway through a render. The frame counts are properties rather than stored
fields, which is what keeps them consistent with the durations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.bbox import validate_bounds
from gpx_animate.domain.style import DEFAULT_STYLE
from gpx_animate.domain.style import Style


SIZE_PRESETS: dict[str, tuple[float, float]] = {
    "16:9": (12.8, 7.2),
    "1:1": (9.0, 9.0),
    "9:16": (7.2, 12.8),
}
"""Output aspect presets, as matplotlib figure sizes in inches."""

DEFAULT_OUTPUT_DIR = Path("output")
"""Where renders land when ``--out`` is not given, relative to the cwd."""


@dataclass(frozen=True)
class RenderConfig:
    """Everything one render needs to know.

    Args:
        style: Basemap style name, resolved by a basemap provider. ``"none"``
            draws no map at all.
        duration: Seconds of the drawing phase.
        hold: Seconds to hold the finished trace. May be zero.
        fps: Frames per second for both phases.
        size: Key into :data:`SIZE_PRESETS`.
        dpi: Resolution of the rendered frames.
        margin: Extra padding around the track bounding box, as a fraction.
        bounds: Optional fixed ``(min_lon, min_lat, max_lon, max_lat)`` window,
            in degrees. When set it replaces the margin-derived view entirely:
            the render is framed to show exactly those bounds, nothing more.
        out: Destination file, or ``None`` to let the output resolver decide.
        output_dir: Directory for the generated name when ``out`` is ``None``.
        force: Overwrite an existing ``out`` instead of suffixing it.
        logo_start: Logo drawn statically on the track's first point.
        logo_end: Logo drawn statically on the track's last point.
        logo_marker: Logo drawn on the head of the growing line, moving with it.
            Each is a registry name or a path to an image; which one, and how
            the logo is sized and anchored, is resolved outside the domain.
        tiff: Optional local GeoTIFF to use instead of downloaded tiles. Wins
            over ``style``, since bringing your own imagery leaves no choice to
            make about a tile server.
        appearance: Colours and font.

    Raises:
        ValueError: If any value is out of range or not a known preset.
    """

    style: str = "topo"
    duration: float = 5.0
    hold: float = 1.0
    fps: int = 30
    size: str = "16:9"
    dpi: int = 150
    margin: float = 0.15
    bounds: Bbox | None = None
    out: Path | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    force: bool = False
    logo_start: str | None = None
    logo_end: str | None = None
    logo_marker: str | None = None
    tiff: Path | None = None
    appearance: Style = DEFAULT_STYLE

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError(f"fps must be > 0, got {self.fps}")
        if self.duration <= 0:
            raise ValueError(f"duration must be > 0, got {self.duration}")
        if self.hold < 0:
            raise ValueError(f"hold must be >= 0, got {self.hold}")
        if self.dpi <= 0:
            raise ValueError(f"dpi must be > 0, got {self.dpi}")
        if self.margin < 0:
            raise ValueError(f"margin must be >= 0, got {self.margin}")
        if self.size not in SIZE_PRESETS:
            raise ValueError(
                f"size must be one of {sorted(SIZE_PRESETS)}, got {self.size!r}"
            )
        for field in ("logo_start", "logo_end", "logo_marker"):
            value = getattr(self, field)
            # The field is a str and not a Path because it may be a registry
            # name instead of a file, so an empty one is a mistake worth
            # reporting: resolving "" would look for a file with no name.
            if value is not None and not value.strip():
                raise ValueError(f"{field} must be a name or a path, not empty")
        if self.bounds is not None:
            validate_bounds(self.bounds)

    @property
    def size_inches(self) -> tuple[float, float]:
        """Figure size in inches as ``(width, height)``."""
        return SIZE_PRESETS[self.size]

    @property
    def total_duration(self) -> float:
        """Length of the finished video in seconds: draw plus hold."""
        return self.duration + self.hold

    @property
    def n_draw_frames(self) -> int:
        """Frames in the drawing phase, truncated to a whole frame.

        The truncation is deliberate and lossy: ``duration=0.19`` at 5 fps is
        zero frames, so the clip comes out shorter than asked. Rounding up
        instead would overshoot every duration.
        """
        return int(self.duration * self.fps)

    @property
    def n_hold_frames(self) -> int:
        """Frames in the hold phase, truncated the same way as the draw phase."""
        return int(self.hold * self.fps)

    @property
    def n_frames(self) -> int:
        """Total frames rendered: the draw phase followed by the hold phase."""
        return self.n_draw_frames + self.n_hold_frames
