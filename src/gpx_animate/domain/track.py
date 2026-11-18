"""Points, tracks and distance over a sphere.

Pure geometry: no file access and no plotting. ``numpy`` is used for the
array-shaped accessors the renderer wants, which is arithmetic, not I/O.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np


EARTH_RADIUS_KM = 6371.0

ELEVATION_SMOOTHING_WINDOW = 5
"""Odd number of samples median- then mean-filtered before gain is summed.

A moving average alone turns a single 50 m GPS spike into a wide 10 m hump --
ten metres of phantom climbing. A median pass first removes isolated spikes,
then the mean pass settles the sample-to-sample jitter that median filtering
leaves behind.
"""

ASCENT_THRESHOLD_M = 2.0
"""Rise, in metres, a filtered profile must gain before it counts as climbing.

Anything smaller is treated as noise. The threshold is used as a hysteresis
band rather than a per-step cutoff, so a long gradual climb made of
sub-threshold steps still accumulates instead of disappearing.
"""

MAX_INTERPOLATED_GAP = 10
"""Most consecutive missing elevations bridged by linear interpolation.

A longer hole is a genuine discontinuity more often than a lost sample -- a
joined track, a device that stopped reporting -- and bridging it would invent a
slope across the gap. Those are left as ``nan`` so the chart breaks its line and
gain is measured on each side. Ten samples is about ten seconds at the usual
1 Hz recording rate.
"""

TrackRow = tuple[float, float, float | None]
"""A ``(longitude, latitude, elevation)`` triple; elevation may be missing."""


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


def _odd_window(length: int) -> int:
    """Return the filter window that fits ``length`` samples, forced odd."""
    window = min(ELEVATION_SMOOTHING_WINDOW, length)
    if window % 2 == 0:
        window -= 1
    return window


def _filtered(values: np.ndarray) -> np.ndarray:
    """Despike and smooth one run of elevations.

    Args:
        values: Elevations in recording order, all present (no gaps).

    Returns:
        The filtered elevations, the same length as ``values``. Runs too short
        to filter come back unchanged.

    Edges are padded with the nearest valid sample so a filter never invents a
    climb at either end by averaging against zero.
    """
    window = _odd_window(len(values))
    if window < 3:
        return values

    pad = window // 2
    windows = np.lib.stride_tricks.sliding_window_view(
        np.pad(values, pad, mode="edge"), window
    )
    despiked = np.median(windows, axis=1)
    padded = np.pad(despiked, pad, mode="edge")
    return np.convolve(padded, np.ones(window) / window, mode="valid")


def _gain_of_run(values: list[float]) -> float:
    """Climbing within one gap-free run, with noise filtered out.

    The hysteresis band is what keeps a gradual climb alive: the reference only
    advances once the profile has risen a full threshold above it, so ten
    one-metre steps count the same as one ten-metre step would.
    """
    if len(values) < 2:
        return 0.0

    filtered = _filtered(np.asarray(values, dtype=float))
    gain = 0.0
    reference = float(filtered[0])
    for sample in filtered[1:]:
        value = float(sample)
        if value > reference:
            if value - reference >= ASCENT_THRESHOLD_M:
                gain += value - reference
                reference = value
        elif reference - value >= ASCENT_THRESHOLD_M:
            reference = value
    return gain


def _runs(values: np.ndarray) -> list[list[float]]:
    """Split elevations at ``nan``, the marker for a gap too long to bridge."""
    return [
        [float(value) for value in group]
        for is_gap, group in itertools.groupby(
            values, key=lambda value: bool(np.isnan(value))
        )
        if not is_gap
    ]


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
    def from_rows(cls, rows: Iterable[TrackRow], name: str = "") -> Track:
        """Build a track from ``(lon, lat, elevation)`` triples.

        Args:
            rows: Triples in recording order. Elevations are metres, and
                ``None`` stays ``None`` so climbing is never counted across a
                gap. Longitudes and latitudes are required.
            name: Display name for the track.

        Returns:
            The assembled track.

        Raises:
            ValueError: If ``rows`` yields no points.
        """
        points = tuple(
            Point(
                lon=float(row[0]),
                lat=float(row[1]),
                elevation=None if row[2] is None else float(row[2]),
            )
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

    def interpolated_elevations(
        self, max_gap: int = MAX_INTERPOLATED_GAP
    ) -> np.ndarray:
        """Elevations with short gaps estimated, for the chart and for gain.

        A missing sample is estimated from its valid neighbours when the hole is
        at most ``max_gap`` samples long. Holes at the start and end of the
        track take the nearest known elevation, because there is only one side
        to estimate from. A longer hole is left as ``nan``: the chart breaks its
        line there and gain is measured on each side, rather than inventing a
        slope across a discontinuity.

        Unlike :attr:`elevations`, which reports 0.0 for every missing sample,
        this is the profile the chart should draw: 0.0 is a sea-level reading,
        not a hole.

        Args:
            max_gap: Longest run of missing samples, in points, that is
                bridged.

        Returns:
            One elevation per point, in metres. A track with no elevation at
            all comes back as zeros, which is also what :attr:`elevations`
            reports and what the chart has always drawn for that case.
        """
        values = self.elevations
        known = np.array(
            [point.elevation is not None for point in self.points], dtype=bool
        )
        indices = np.flatnonzero(known)
        if indices.size == 0:
            return values

        # There is nothing on the far side of an edge gap to interpolate from,
        # so hold the nearest known value instead of leaving a cliff.
        values[: indices[0]] = values[indices[0]]
        values[indices[-1] + 1 :] = values[indices[-1]]

        for left, right in zip(indices, indices[1:], strict=False):
            gap = right - left - 1
            if gap == 0:
                continue
            if gap > max_gap:
                values[left + 1 : right] = np.nan
            else:
                ramp = np.linspace(values[left], values[right], gap + 2)
                values[left + 1 : right] = ramp[1:-1]
        return values

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
        """Total climbing in metres, with GPS noise filtered out.

        Short gaps are interpolated first (:meth:`interpolated_elevations`), so
        a lost sample on a climb is estimated rather than treated as a drop to
        sea level. Consecutive samples are then despiked, smoothed and summed
        through a hysteresis band (:data:`ASCENT_THRESHOLD_M`), because raw
        sample-to-sample rises are dominated by altitude noise: a metre or two of
        barometric jitter per sample adds up to hundreds of phantom metres over
        a long track. A gap too long to bridge splits the profile, so nothing is
        counted across it.

        Returns:
            The climbing in metres. Descents are not subtracted.
        """
        return sum(_gain_of_run(run) for run in _runs(self.interpolated_elevations()))
