"""The load_track use case: GPX parsing and its error paths."""

import gpxpy
import gpxpy.gpx
import pytest

from gpx_animate.application.errors import GpxAnimateError
from gpx_animate.application.errors import NoPointsError
from gpx_animate.application.use_cases.load_track import load_track
from gpx_animate.domain.track import Track


class TestSuccess:
    def test_reads_the_fixture(self, short_track_gpx):
        track = load_track(short_track_gpx)
        assert isinstance(track, Track)
        assert len(track.points) == 15

    def test_uses_the_name_from_the_file_metadata(self, short_track_gpx):
        assert load_track(short_track_gpx).name == "Test Track"

    def test_falls_back_to_a_title_cased_stem(self, tmp_path):
        gpx = tmp_path / "my_long_ride.gpx"
        gpx.write_text(
            '<gpx version="1.1" creator="test">'
            "<trk><trkseg>"
            '<trkpt lat="45.0" lon="7.0"/><trkpt lat="45.1" lon="7.1"/>'
            "</trkseg></trk></gpx>"
        )
        assert load_track(gpx).name == "My Long Ride"

    def test_keeps_elevations(self, short_track_gpx):
        track = load_track(short_track_gpx)
        assert track.elevations[0] == 100.0
        assert track.elevations.max() > track.elevations.min()

    def test_missing_elevation_becomes_zero(self, tmp_path):
        gpx = tmp_path / "flat.gpx"
        gpx.write_text(
            '<gpx version="1.1" creator="test">'
            "<trk><trkseg>"
            '<trkpt lat="45.0" lon="7.0"/><trkpt lat="45.1" lon="7.1"/>'
            "</trkseg></trk></gpx>"
        )
        assert load_track(gpx).elevations.tolist() == [0.0, 0.0]

    def test_flattens_every_track_and_segment(self, tmp_path):
        """GPX allows several tracks, each with several segments.

        All of them are drawn as one polyline, which contradicts README 7's
        claim that only the first is used.
        """
        gpx = tmp_path / "multi.gpx"
        gpx.write_text(
            '<gpx version="1.1" creator="test">'
            "<trk><trkseg>"
            '<trkpt lat="45.0" lon="7.0"/><trkpt lat="45.1" lon="7.1"/>'
            "</trkseg><trkseg>"
            '<trkpt lat="45.2" lon="7.2"/><trkpt lat="45.3" lon="7.3"/>'
            "</trkseg></trk>"
            "<trk><trkseg>"
            '<trkpt lat="46.0" lon="8.0"/><trkpt lat="46.1" lon="8.1"/>'
            "</trkseg></trk></gpx>"
        )
        assert len(load_track(gpx).points) == 6

    def test_falls_back_to_routes(self, route_only_gpx):
        track = load_track(route_only_gpx)
        assert len(track.points) == 3
        assert track.total_distance_km() > 0

    def test_geometry_is_computed_on_load(self, short_track_gpx):
        track = load_track(short_track_gpx)
        assert track.total_distance_km() > 0
        assert track.elevation_gain_m() > 0


class TestFailure:
    def test_waypoint_only_is_rejected(self, waypoints_only_gpx):
        """Waypoints are not a path, so they are not turned into one."""
        with pytest.raises(NoPointsError, match="No track/route points found"):
            load_track(waypoints_only_gpx)

    def test_empty_track_is_rejected(self, tmp_path):
        gpx = tmp_path / "empty.gpx"
        gpx.write_text('<gpx version="1.1" creator="test"><trk/></gpx>')
        with pytest.raises(NoPointsError):
            load_track(gpx)

    def test_malformed_xml_raises(self, malformed_gpx):
        with pytest.raises(gpxpy.gpx.GPXXMLSyntaxException):
            load_track(malformed_gpx)

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            load_track(tmp_path / "nope.gpx")

    def test_the_error_is_catchable_as_a_value_error(self, waypoints_only_gpx):
        """NoPointsError subclasses ValueError, as the old code raised it."""
        with pytest.raises(ValueError):
            load_track(waypoints_only_gpx)

    def test_the_error_names_the_file(self, waypoints_only_gpx):
        with pytest.raises(GpxAnimateError, match=str(waypoints_only_gpx)):
            load_track(waypoints_only_gpx)
