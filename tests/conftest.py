"""Shared fixtures for the gpx_animate test suite."""

from pathlib import Path

import pytest

from gpx_animate.config.defaults import default_config
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Point
from gpx_animate.domain.track import Track


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


@pytest.fixture
def fast_config() -> RenderConfig:
    """A config that renders a handful of small frames quickly.

    Two draw frames and one hold frame at 5 fps, at 20 dpi. Anything slower
    makes the suite crawl without testing anything new.
    """
    config = default_config()
    return RenderConfig(
        style=config.style,
        duration=0.4,
        hold=0.2,
        fps=5,
        size="1:1",
        dpi=20,
    )


@pytest.fixture
def track() -> Track:
    """A six-point track that climbs steadily and wiggles in latitude."""
    return Track(
        points=(
            Point(lon=7.00, lat=45.00, elevation=100.0),
            Point(lon=7.01, lat=45.01, elevation=110.0),
            Point(lon=7.02, lat=45.00, elevation=105.0),
            Point(lon=7.03, lat=45.02, elevation=130.0),
            Point(lon=7.04, lat=45.01, elevation=125.0),
            Point(lon=7.05, lat=45.03, elevation=140.0),
        ),
        name="Trip",
    )
