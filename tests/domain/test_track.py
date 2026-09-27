"""Geometry: haversine correctness, cumulative distance, elevation gain."""

import math

import numpy as np
import pytest

from gpx_animate.domain.track import EARTH_RADIUS_KM
from gpx_animate.domain.track import Point
from gpx_animate.domain.track import Track
from gpx_animate.domain.track import haversine_km


def one_degree_of_latitude() -> float:
    """Distance covered by one degree of latitude, by definition of a degree."""
    return math.pi * EARTH_RADIUS_KM / 180.0


class TestHaversine:
    def test_one_degree_of_latitude(self):
        assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(
            one_degree_of_latitude(), rel=1e-9
        )

    def test_a_degree_of_longitude_shrinks_with_latitude(self):
        """At 60 degrees north a longitude degree is about half as wide."""
        equator = haversine_km(0.0, 0.0, 1.0, 0.0)
        north = haversine_km(0.0, 60.0, 1.0, 60.0)
        assert north == pytest.approx(equator / 2, rel=1e-3)

    def test_known_city_pair(self):
        """London to Paris is about 344 km."""
        assert haversine_km(-0.1276, 51.5074, 2.3522, 48.8566) == pytest.approx(
            343.5, abs=1.0
        )

    def test_is_symmetric(self):
        assert haversine_km(7.0, 45.0, 7.5, 45.5) == pytest.approx(
            haversine_km(7.5, 45.5, 7.0, 45.0)
        )

    def test_antipodes_are_half_the_circumference(self):
        assert haversine_km(0.0, 0.0, 180.0, 0.0) == pytest.approx(
            math.pi * EARTH_RADIUS_KM, rel=1e-9
        )

    def test_identical_points_are_zero(self):
        assert haversine_km(7.0, 45.0, 7.0, 45.0) == 0.0

    def test_short_distance_is_roughly_euclidean(self):
        """Near the origin the great circle and the flat plane agree."""
        assert haversine_km(0.0, 0.0, 0.01, 0.0) == pytest.approx(1.112, abs=0.01)

    def test_crosses_the_antimeridian_the_short_way(self):
        """179.9E to 179.9W is 0.2 degrees apart, not 359.8."""
        assert haversine_km(179.9, 0.0, -179.9, 0.0) == pytest.approx(
            haversine_km(0.0, 0.0, 0.2, 0.0), rel=1e-9
        )


class TestTrackConstruction:
    def test_from_rows_keeps_order_and_values(self):
        track = Track.from_rows([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)], name="T")
        assert track.name == "T"
        assert track.points == (
            Point(1.0, 2.0, 3.0),
            Point(4.0, 5.0, 6.0),
        )

    def test_a_falsy_elevation_becomes_zero(self):
        track = Track.from_rows([(1.0, 2.0, 0.0), (4.0, 5.0, 0.0)])
        assert track.elevations.tolist() == [0.0, 0.0]

    def test_an_empty_track_is_rejected(self):
        """No points means no bounding box and nothing to draw."""
        with pytest.raises(ValueError, match="at least one point"):
            Track(points=(), name="empty")

    def test_a_single_point_track_is_allowed(self):
        """It draws a dot; it just cannot animate."""
        track = Track.from_rows([(7.0, 45.0, 100.0)])
        assert len(track.points) == 1
        assert track.total_distance_km() == 0.0

    def test_array_accessors_are_float_arrays(self, track: Track):
        assert track.longitudes.dtype == float
        assert track.longitudes.tolist() == [7.00, 7.01, 7.02, 7.03, 7.04, 7.05]
        assert track.latitudes.tolist() == [45.00, 45.01, 45.00, 45.02, 45.01, 45.03]
        assert track.elevations.tolist() == [100.0, 110.0, 105.0, 130.0, 125.0, 140.0]

    def test_none_elevation_reads_as_zero_in_the_array(self):
        track = Track(points=(Point(7.0, 45.0), Point(7.1, 45.1)))
        assert track.elevations.tolist() == [0.0, 0.0]

    def test_is_frozen(self, track: Track):
        with pytest.raises(AttributeError):
            track.name = "renamed"  # ty: ignore[invalid-assignment]


class TestCumulativeDistance:
    def test_starts_at_zero(self, track: Track):
        assert track.cumulative_distance_km()[0] == 0.0

    def test_is_monotonic(self, track: Track):
        distances = track.cumulative_distance_km()
        assert all(b >= a for a, b in zip(distances, distances[1:], strict=False))

    def test_sums_the_legs(self, track: Track):
        legs = [
            haversine_km(a.lon, a.lat, b.lon, b.lat)
            for a, b in zip(track.points, track.points[1:], strict=False)
        ]
        assert track.total_distance_km() == pytest.approx(sum(legs))

    def test_duplicate_points_add_nothing(self):
        track = Track.from_rows([(7.0, 45.0, 100.0)] * 4)
        assert track.total_distance_km() == 0.0

    def test_single_point_is_zero(self):
        assert Track.from_rows([(7.0, 45.0, 0.0)]).total_distance_km() == 0.0

    def test_out_and_back_is_double_the_leg(self):
        """Distance accumulates on the way home; it is not net displacement."""
        track = Track.from_rows([(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)])
        assert track.total_distance_km() == pytest.approx(
            2 * one_degree_of_latitude(), rel=1e-9
        )


class TestElevationGain:
    def test_sums_only_the_climbing_steps(self, track: Track):
        assert track.elevation_gain_m() == pytest.approx(10.0 + 25.0 + 15.0)

    def test_flat_track_has_no_gain(self):
        assert (
            Track.from_rows([(0.0, 0.0, 50.0), (0.1, 0.0, 50.0)]).elevation_gain_m()
            == 0.0
        )

    def test_descent_does_not_subtract(self):
        """Gain is a sum of rises, so a net descent still reports 0."""
        track = Track.from_rows([(0.0, 0.0, 300.0), (0.1, 0.0, 100.0)])
        assert track.elevation_gain_m() == 0.0

    def test_single_point_has_no_gain(self):
        assert Track.from_rows([(0.0, 0.0, 900.0)]).elevation_gain_m() == 0.0

    def test_duplicate_points_add_nothing(self):
        track = Track.from_rows([(0.0, 0.0, 10.0), (0.0, 0.0, 10.0)])
        assert track.elevation_gain_m() == 0.0

    def test_missing_elevation_does_not_create_gain(self):
        track = Track(points=(Point(0.0, 0.0), Point(0.1, 0.1, 500.0)))
        assert track.elevation_gain_m() == pytest.approx(500.0)


class TestNumpyInterop:
    def test_arrays_feed_pyproj_unchanged(self, track: Track):
        """The renderer projects these directly, so they must be plain arrays."""
        assert isinstance(track.longitudes, np.ndarray)
        assert track.longitudes.ndim == 1
