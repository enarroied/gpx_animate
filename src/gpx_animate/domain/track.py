"""Points, tracks and distance over a sphere.

Pure geometry: no file access and no plotting. ``numpy`` is used for the
array-shaped accessors the renderer wants, which is arithmetic, not I/O.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np


EARTH_RADIUS_KM = 6371.0


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in kilometres between two lon/lat pairs.

    Args:
        lon1: Longitude of the first point, in degrees.
        lat1: Latitude of the first point, in degrees.
        lon2: Longitude of the second point, in degrees.
        lat2: Latitude of the second point, in degrees.

    Returns:
        The distance in kilometres.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Point:
    """A single recorded position."""

    lon: float
    lat: float
    elevation: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Track:
    """An ordered sequence of points, flattened across GPX tracks.

    Args:
        points: The positions, in recording order. Must not be empty.
        name: Display name, usually the GPX file's own name.

    Raises:
        ValueError: If ``points`` is empty. A track with no points has no
            bounding box and nothing to draw.
    """

    points: tuple[Point, ...]
    name: str = ""

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("Track requires at least one point")

    @classmethod
    def from_rows(cls, rows: Iterable[Sequence[float]], name: str = "") -> Track:
        """Build a track from ``(lon, lat, elevation)`` triples.

        Args:
            rows: Triples in recording order. Elevations are metres, and a
                falsy one becomes 0.0. Normalising a GPX's absent ``<ele>`` is
                :func:`~gpx_animate.application.use_cases.load_track.load_track`'s
                job, so nothing here has to cope with ``None``.
            name: Display name for the track.

        Returns:
            The assembled track.

        Raises:
            ValueError: If ``rows`` yields no points.
        """
        points = tuple(
            Point(lon=float(row[0]), lat=float(row[1]), elevation=float(row[2] or 0.0))
            for row in rows
        )
        return cls(points=points, name=name)

    @property
    def longitudes(self) -> np.ndarray:
        """Longitudes as a float array."""
        return np.array([p.lon for p in self.points], dtype=float)

    @property
    def latitudes(self) -> np.ndarray:
        """Latitudes as a float array."""
        return np.array([p.lat for p in self.points], dtype=float)

    @property
    def elevations(self) -> np.ndarray:
        """Elevations in metres as a float array, with 0.0 for missing values."""
        return np.array(
            [p.elevation if p.elevation is not None else 0.0 for p in self.points],
            dtype=float,
        )

    def cumulative_distance_km(self) -> tuple[float, ...]:
        """Distance from the start to each point, in kilometres.

        Returns:
            One value per point; the first is always 0.0.
        """
        distances = [0.0]
        for previous, current in zip(self.points, self.points[1:], strict=False):
            distances.append(
                distances[-1]
                + haversine_km(previous.lon, previous.lat, current.lon, current.lat)
            )
        return tuple(distances)

    def total_distance_km(self) -> float:
        """Length of the whole track in kilometres."""
        return self.cumulative_distance_km()[-1]

    def elevation_gain_m(self) -> float:
        """Total climbing in metres, summing only the ascending steps."""
        gain = 0.0
        for previous, current in zip(self.points, self.points[1:], strict=False):
            if (current.elevation or 0.0) > (previous.elevation or 0.0):
                gain += (current.elevation or 0.0) - (previous.elevation or 0.0)
        return gain
