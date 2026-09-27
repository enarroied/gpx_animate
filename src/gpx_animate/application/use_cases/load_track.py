"""Load a GPX file into a :class:`~gpx_animate.domain.track.Track`."""

from __future__ import annotations

import logging
from pathlib import Path

import gpxpy

from gpx_animate.application.errors import NoPointsError
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)


def load_track(gpx_path: Path) -> Track:
    """Read every track, segment and route in a GPX file as one track.

    The GPX spec allows several tracks and several segments per track. All of
    them are flattened into a single polyline in file order, which is what the
    renderer can draw; a file with a single track is the common case and is
    indistinguishable from the flattened result.

    Args:
        gpx_path: The GPX file to read.

    Returns:
        The track, named after the file's own ``<name>`` or its stem.

    Raises:
        NoPointsError: If the file contains no track or route points. A
            waypoint-only file lands here too: waypoints are not a path, so
            they are not turned into one.
        gpxpy.GPXParseException: Propagated unchanged from gpxpy when the XML
            is malformed.
    """
    with gpx_path.open() as handle:
        gpx = gpxpy.parse(handle)

    name = gpx.name or gpx_path.stem.replace("_", " ").title()
    rows = [
        (point.longitude, point.latitude, point.elevation or 0.0)
        for track in gpx.tracks
        for segment in track.segments
        for point in segment.points
    ]

    if not rows:
        # Fall back to routes: planners export a planned path that way.
        rows = [
            (point.longitude, point.latitude, point.elevation or 0.0)
            for route in gpx.routes
            for point in route.points
        ]

    if not rows:
        raise NoPointsError(f"No track/route points found in {gpx_path}")

    logger.info("Loaded %d points from %s", len(rows), gpx_path)
    return Track.from_rows(rows, name=name)
