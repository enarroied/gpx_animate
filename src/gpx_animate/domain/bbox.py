"""The bounding box of a view, and the padding rule that grows it.

It lives in the domain because it is pure arithmetic on four numbers, and
because both the renderer and every :class:`~gpx_animate.application.ports.BasemapProvider`
need to agree on the *order* of those four. Getting that order wrong is silent:
matplotlib, contextily and GeoTIFF all describe a rectangle, in three different
conventions, and a swap shows up as a basemap that is mirrored or quartered
rather than as an error.
"""

from __future__ import annotations

from typing import NamedTuple


class Bbox(NamedTuple):
    """An axis-aligned rectangle as ``(min_x, min_y, max_x, max_y)``.

    This is the west-south-east-north order, the one GeoJSON and nearly every
    bounds API use, and the one the basemap port takes. It is *not* matplotlib's
    ``extent`` order, which is left-right-bottom-top; the conversion happens
    once, in the renderer.

    Args:
        min_x: Western edge.
        min_y: Southern edge.
        max_x: Eastern edge.
        max_y: Northern edge.
    """

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __repr__(self) -> str:
        """Show plain floats rather than numpy scalars.

        Boxes are built from numpy values, and numpy 2 reprs as
        ``np.float64(1.0)``. That is fine in a log line but not in the
        user-facing "the GeoTIFF is for somewhere else" message, so the four
        edges are formatted as the floats the annotations already claim they are.
        """
        edges = ", ".join(
            f"{name}={float(value)!r}"
            for name, value in zip(self._fields, self, strict=True)
        )
        return f"Bbox({edges})"

    @property
    def width(self) -> float:
        """Extent along x, in projected units."""
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        """Extent along y, in projected units."""
        return self.max_y - self.min_y

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """The same rectangle in matplotlib's ``(left, right, bottom, top)`` order."""
        return (self.min_x, self.max_x, self.min_y, self.max_y)

    def contains(self, other: Bbox) -> bool:
        """Whether ``other`` lies entirely inside this box.

        Args:
            other: The box to test.

        Returns:
            True if ``other`` fits without poking out on any edge.
        """
        return (
            self.min_x <= other.min_x
            and self.min_y <= other.min_y
            and self.max_x >= other.max_x
            and self.max_y >= other.max_y
        )

    def overlaps(self, other: Bbox) -> bool:
        """Whether the two boxes share any location.

        Used to reject a basemap that covers a different part of the world: the
        boxes can be far apart and the check is one line, whereas noticing a
        blank frame at the end is not.

        Args:
            other: The box to test.

        Returns:
            True if the boxes share at least one point. Boxes that merely touch
            along an edge share none, so they do not count; a box with no area
            does count where it sits inside the other, which is what keeps a
            single-point track from being told its GeoTIFF is in the wrong place.
        """
        return (
            self.min_x < other.max_x
            and other.min_x < self.max_x
            and self.min_y < other.max_y
            and other.min_y < self.max_y
        )

    def padded(self, fraction: float) -> Bbox:
        """Grow the box by a fraction of its own size on every side.

        Every axis gets at least a one-unit pad, including when ``fraction`` is
        zero: a degenerate box, one with no extent on an axis, would otherwise
        ask matplotlib to draw a view of zero width, and dividing to work out the
        padding for a single-point track is how you get an infinity. The cost of
        the floor is that ``--margin 0`` still shows a metre of breathing room,
        which is what the renderer has always done.

        Args:
            fraction: Padding as a fraction of the box's size, e.g. ``0.15``.

        Returns:
            The padded box.

        Raises:
            ValueError: If ``fraction`` is negative.
        """
        if fraction < 0:
            raise ValueError(f"fraction must be >= 0, got {fraction}")
        pad_x = self.width * fraction or 1.0
        pad_y = self.height * fraction or 1.0
        return Bbox(
            self.min_x - pad_x,
            self.min_y - pad_y,
            self.max_x + pad_x,
            self.max_y + pad_y,
        )


def validate_bounds(bounds: Bbox) -> None:
    """Raise if a box is not a valid lon/lat window for ``--bounds``.

    Bounds arrive as ``min_lon,min_lat,max_lon,max_lat``, degrees of WGS84.
    Both the parser and :class:`~gpx_animate.domain.render_config.RenderConfig`
    check here, so a programmatic call and a parsed flag reject the same boxes.
    A box rejected here is also one that cannot be projected sanely: a latitude
    beyond 90 or longitude beyond 180 does not exist on the spheroid, and a
    reversed edge would project to a valid but empty-looking view.

    Args:
        bounds: The box to check. Left untouched.

    Raises:
        ValueError: If a longitude is outside ``[-180, 180]``, a latitude
            outside ``[-90, 90]``, or an edge is not ordered min < max.
    """
    if not (-180 <= bounds.min_x <= 180 and -180 <= bounds.max_x <= 180):
        raise ValueError(
            f"bounds longitudes must be in [-180, 180], got {bounds.min_x}, "
            f"{bounds.max_x}"
        )
    if not (-90 <= bounds.min_y <= 90 and -90 <= bounds.max_y <= 90):
        raise ValueError(
            f"bounds latitudes must be in [-90, 90], got {bounds.min_y}, {bounds.max_y}"
        )
    if bounds.min_x >= bounds.max_x or bounds.min_y >= bounds.max_y:
        raise ValueError(f"bounds must have min < max on both axes, got {bounds}")


def parse_bounds(text: str) -> Bbox:
    """Parse a ``--bounds`` value into a validated box.

    The argument is the ``min_lon,min_lat,max_lon,max_lat`` of the flag, four
    comma-separated degrees that fix the view instead of letting the margin pad
    the track. Parsing is a pure string-to-box function rather than argparse
    glue so the same value works in a config file and the environment, and so
    the error is a :exc:`ValueError` the CLI turns into exit code 1 like every
    other bad knob.

    Args:
        text: Four comma-separated numbers, e.g. ``"2.35,48.85,2.40,48.90"``.

    Returns:
        The box, validated by :func:`validate_bounds`.

    Raises:
        ValueError: If there are not four numbers, or the box fails
            :func:`validate_bounds`.
    """
    try:
        values = [float(part) for part in text.split(",")]
    except ValueError as error:
        raise ValueError(
            f"bounds must be four comma-separated numbers, got {text!r}"
        ) from error
    if len(values) != 4:
        raise ValueError(
            f"bounds must be four numbers (min_lon,min_lat,max_lon,max_lat), "
            f"got {len(values)}: {text!r}"
        )
    bounds = Bbox(*values)
    validate_bounds(bounds)
    return bounds
