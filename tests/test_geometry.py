"""Geometry helpers: haversine distance, cumulative distance, elevation gain.

These are the only pure functions in the monolith, so they carry the most
value per test: a wrong haversine silently scales every distance in the HUD.
"""

import math

import numpy as np
import pytest
from gpx_animate import cumulative_distance_km
from gpx_animate import cumulative_gain_m
from gpx_animate import haversine_km


# A degree of latitude is a fixed arc of the great circle: 2*pi*R/360.
DEG_TO_KM = 2 * math.pi * 6371.0 / 360.0

# (lon, lat) — the argument order haversine_km expects.
LONDON = (-0.1278, 51.5074)
PARIS = (2.3522, 48.8566)


class TestHaversine:
    def test_one_degree_of_latitude(self):
        assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(DEG_TO_KM, abs=1e-6)

    def test_one_degree_of_longitude_at_the_equator(self):
        # At the equator a degree of longitude spans the same arc as a degree
        # of latitude, which is what makes Mercator tiles square-ish.
        assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(DEG_TO_KM, abs=1e-6)

    def test_degree_of_longitude_shrinks_by_cosine_of_latitude(self):
        assert haversine_km(0.0, 60.0, 1.0, 60.0) == pytest.approx(
            DEG_TO_KM * 0.5, abs=1e-3
        )

    def test_known_city_pair(self):
        assert haversine_km(*LONDON, *PARIS) == pytest.approx(343.556, abs=0.01)

    def test_identical_points_are_zero(self):
        assert haversine_km(12.3, 45.6, 12.3, 45.6) == 0.0

    def test_is_symmetric(self):
        assert haversine_km(*LONDON, *PARIS) == pytest.approx(
            haversine_km(*PARIS, *LONDON)
        )

    def test_antipodal_points_are_half_the_circumference(self):
        assert haversine_km(0.0, 0.0, 180.0, 0.0) == pytest.approx(
            math.pi * 6371.0, rel=1e-6
        )


class TestCumulativeDistance:
    def test_empty_track(self):
        assert cumulative_distance_km(np.array([]), np.array([])).tolist() == []

    def test_single_point_starts_at_zero(self):
        dists = cumulative_distance_km(np.array([7.0]), np.array([45.0]))
        assert dists.tolist() == [0.0]

    def test_first_point_is_always_zero(self):
        dists = cumulative_distance_km(np.array([7.0, 7.1, 7.2]), np.array([45.0] * 3))
        assert dists[0] == 0.0

    def test_total_equals_the_sum_of_the_steps(self):
        lons = np.array([7.0, 7.1, 7.2, 7.3])
        lats = np.array([45.0, 45.1, 45.0, 45.2])
        steps = [
            haversine_km(lons[i - 1], lats[i - 1], lons[i], lats[i])
            for i in range(1, len(lons))
        ]
        dists = cumulative_distance_km(lons, lats)
        assert dists[-1] == pytest.approx(sum(steps))

    def test_is_monotonic_non_decreasing(self):
        lons = np.array([7.0, 7.1, 7.0, 7.2, 7.05])
        lats = np.array([45.0, 45.1, 44.9, 45.2, 45.0])
        dists = cumulative_distance_km(lons, lats)
        assert all(b >= a for a, b in zip(dists, dists[1:], strict=False))

    def test_duplicate_points_do_not_inflate_the_total(self):
        """A stationary GPS logger emits repeats; they must add zero distance."""
        lons = np.array([7.0, 7.0, 7.0, 7.1])
        lats = np.array([45.0, 45.0, 45.0, 45.0])
        dists = cumulative_distance_km(lons, lats)
        one_hop = haversine_km(7.0, 45.0, 7.1, 45.0)
        assert dists.tolist() == [0.0, 0.0, 0.0, pytest.approx(one_hop)]


class TestCumulativeGain:
    def test_flat_track_has_no_gain(self):
        assert cumulative_gain_m(np.array([100.0, 100.0, 100.0])) == 0.0

    def test_only_ascent_is_counted(self):
        # 0->10 gains 10, 10->5 gains nothing, 5->20 gains 15.
        assert cumulative_gain_m(np.array([0.0, 10.0, 5.0, 20.0])) == 25.0

    def test_pure_descent_has_no_gain(self):
        assert cumulative_gain_m(np.array([100.0, 80.0, 60.0])) == 0.0

    def test_empty_track(self):
        assert cumulative_gain_m(np.array([])) == 0.0

    def test_single_point(self):
        assert cumulative_gain_m(np.array([500.0])) == 0.0
