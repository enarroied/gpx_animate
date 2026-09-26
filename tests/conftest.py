"""Shared fixtures for the gpx_animate test suite."""

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def short_track_gpx() -> Path:
    """A valid 15-point track with a <metadata><name> and elevations."""
    return FIXTURES / "short_track.gpx"


@pytest.fixture(scope="session")
def route_only_gpx() -> Path:
    """A valid GPX with a route and no track."""
    return FIXTURES / "route_only.gpx"


@pytest.fixture(scope="session")
def waypoints_only_gpx() -> Path:
    """A valid GPX with only waypoints, which load_track ignores."""
    return FIXTURES / "waypoints_only.gpx"


@pytest.fixture(scope="session")
def malformed_gpx() -> Path:
    """Truncated XML, so parsing raises."""
    return FIXTURES / "malformed.gpx"


@pytest.fixture(scope="session")
def logo_png() -> Path:
    """A 16x16 RGBA PNG with real transparency."""
    return FIXTURES / "logo.png"
