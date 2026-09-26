"""GPX parsing: tracks, routes, error paths, and the quirks load_track has."""

import pytest
from gpx_animate import load_track
from gpxpy.gpx import GPXXMLSyntaxException


GPX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
{body}
</gpx>
"""


def write_gpx(tmp_path, body: str, name: str = "case.gpx"):
    path = tmp_path / name
    path.write_text(GPX_TEMPLATE.format(body=body))
    return path


class TestHappyPath:
    def test_returns_arrays_and_a_name(self, short_track_gpx):
        lons, lats, ele, name = load_track(short_track_gpx)
        assert name == "Test Track"
        assert len(lons) == len(lats) == len(ele) == 15

    def test_first_point_matches_the_fixture(self, short_track_gpx):
        lons, lats, ele, _ = load_track(short_track_gpx)
        assert lons[0] == pytest.approx(7.0)
        assert lats[0] == pytest.approx(45.0)
        assert ele[0] == pytest.approx(100.0)

    def test_name_falls_back_to_the_filename(self, tmp_path):
        path = write_gpx(
            tmp_path,
            '<trk><trkseg><trkpt lat="1.0" lon="2.0"/></trkseg></trk>',
            name="my_little_trip.gpx",
        )
        _, _, _, name = load_track(path)
        assert name == "My Little Trip"

    def test_missing_elevation_becomes_zero(self, tmp_path):
        path = write_gpx(
            tmp_path, '<trk><trkseg><trkpt lat="1.0" lon="2.0"/></trkseg></trk>'
        )
        _, _, ele, _ = load_track(path)
        assert ele.tolist() == [0.0]


class TestFallbacksAndFlattening:
    def test_falls_back_to_routes_when_there_is_no_track(self, route_only_gpx):
        lons, lats, _, name = load_track(route_only_gpx)
        assert name == "Route Only"
        assert len(lons) == 3
        assert lons[0] == pytest.approx(7.0)

    def test_tracks_win_over_routes_when_both_exist(self, tmp_path):
        path = write_gpx(
            tmp_path,
            '<trk><trkseg><trkpt lat="1.0" lon="2.0"/>'
            '<trkpt lat="1.1" lon="2.1"/></trkseg></trk>'
            '<rte><rtept lat="9.0" lon="9.0"/></rte>',
        )
        lons, _, _, _ = load_track(path)
        assert len(lons) == 2

    def test_multiple_tracks_and_segments_are_concatenated(self, tmp_path):
        """Real behaviour: all tracks and segments become one polyline.

        README 7 claims "only the first track/segment is used", which is wrong.
        """
        path = write_gpx(
            tmp_path,
            "<trk>"
            '<trkseg><trkpt lat="1.0" lon="2.0"/><trkpt lat="1.1" lon="2.1"/></trkseg>'
            '<trkseg><trkpt lat="1.2" lon="2.2"/></trkseg>'
            "</trk>"
            "<trk>"
            '<trkseg><trkpt lat="3.0" lon="4.0"/></trkseg>'
            "</trk>",
        )
        lons, _, _, _ = load_track(path)
        assert len(lons) == 4

    def test_segment_order_is_preserved(self, tmp_path):
        path = write_gpx(
            tmp_path,
            "<trk>"
            '<trkseg><trkpt lat="1.0" lon="2.0"/></trkseg>'
            '<trkseg><trkpt lat="3.0" lon="4.0"/></trkseg>'
            "</trk>",
        )
        lons, _, _, _ = load_track(path)
        assert lons.tolist() == [2.0, 4.0]

    def test_multiple_tracks_are_concatenated(self, tmp_path):
        path = write_gpx(
            tmp_path,
            '<trk><trkseg><trkpt lat="1.0" lon="2.0"/></trkseg></trk>'
            '<trk><trkseg><trkpt lat="3.0" lon="4.0"/></trkseg></trk>',
        )
        lons, _, _, _ = load_track(path)
        assert len(lons) == 2


class TestErrors:
    def test_waypoints_only_is_rejected(self, waypoints_only_gpx):
        """load_track reads tracks then routes, and never touches waypoints."""
        with pytest.raises(ValueError, match="No track/route points"):
            load_track(waypoints_only_gpx)

    def test_gpx_with_nothing_in_it_is_rejected(self, tmp_path):
        path = write_gpx(tmp_path, "")
        with pytest.raises(ValueError, match="No track/route points"):
            load_track(path)

    def test_malformed_xml_raises_a_parse_error(self, malformed_gpx):
        with pytest.raises(GPXXMLSyntaxException):
            load_track(malformed_gpx)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_track(tmp_path / "nope.gpx")
