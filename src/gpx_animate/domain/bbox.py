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
