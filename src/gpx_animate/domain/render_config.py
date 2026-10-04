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

PROFILE_EDGE_MARGIN = 0.02
"""Axes fraction kept clear between a corner chart and the frame edge."""

PROFILE_POSITIONS: dict[str, tuple[str, float, float]] = {
    "off": ("", 0.5, 0.5),
    "top": ("upper left", 0.5, 1.0),
    "bottom": ("lower left", 0.5, 0.0),
    "top-left": ("upper left", 0.0, 1.0),
    "top-right": ("upper left", 1.0, 1.0),
    "bottom-left": ("lower left", 0.0, 0.0),
    "bottom-right": ("lower left", 1.0, 0.0),
}
"""Where the elevation chart sits, as ``(loc, x_anchor, y_anchor)``.

The two anchors are read independently so a corner needs no special-casing, and
a centre anchor centres the panel -- which is how a future middle position stays
honest instead of falling through to whichever branch was written last. A
mutable dict on purpose: it is the single source of truth for ``--profile``'s
allowed values, and tests add entries to check the general rules.
"""

FULL_WIDTH_PROFILE_POSITIONS = frozenset({"top", "bottom"})
"""Positions that span the frame and therefore ignore ``profile_width``."""


@dataclass(frozen=True)
class GifConfig:
    """GIF export settings."""

    enabled: bool = False
    size: str = "800x450"
    fps: int = 15
    colors: int = 128
    dither: bool = False
    loop: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.size, str) or "x" not in self.size:
            raise ValueError(f"size must be WIDTHxHEIGHT, got {self.size!r}")
        try:
            w_str, h_str = self.size.split("x", 1)
            w = int(w_str)
            h = int(h_str)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"size must be WIDTHxHEIGHT, got {self.size!r}") from exc
        if w <= 0 or h <= 0:
            raise ValueError(f"size must be positive, got {self.size!r}")
        if self.fps <= 0:
            raise ValueError(f"fps must be > 0, got {self.fps}")
        if self.colors not in (64, 128, 256):
            raise ValueError(f"colors must be 64, 128, or 256, got {self.colors}")
        if self.loop < 0:
            raise ValueError(f"loop must be >= 0, got {self.loop}")

    @property
    def width(self) -> int:
        w_str, _ = self.size.split("x", 1)
        return int(w_str)

    @property
    def height(self) -> int:
        _, h_str = self.size.split("x", 1)
        return int(h_str)


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
        logo_size_px: Width in device pixels for the resolutions above, applied
            to every placement. ``None`` keeps the size resolved from the logo
            registry or the default size for bare paths.
        logo_plate_padding: Padding fraction for the white plate behind logos.
            ``0.0`` means no plate.
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
    logo_size_px: int | None = None
    logo_plate_padding: float = 0.0
    tiff: Path | None = None
    appearance: Style = DEFAULT_STYLE
    gif: GifConfig = GifConfig()
    profile: str = "off"
    profile_width: float = 0.28
    profile_height: float = 0.15
    chart_video: bool = False

    def __post_init__(self) -> None:  # noqa: PLR0912
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
        if self.logo_size_px is not None and self.logo_size_px <= 0:
            raise ValueError(f"logo_size_px must be > 0, got {self.logo_size_px}")
        if self.logo_plate_padding < 0:
            raise ValueError(
                f"logo_plate_padding must be >= 0, got {self.logo_plate_padding}"
            )
        if self.profile not in PROFILE_POSITIONS:
            raise ValueError(
                f"profile must be one of {sorted(PROFILE_POSITIONS)}, "
                f"got {self.profile!r}"
            )
        for field in ("profile_width", "profile_height"):
            value = getattr(self, field)
            if value <= 0 or value >= 1:
                raise ValueError(f"{field} must be between 0 and 1, got {value}")
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
