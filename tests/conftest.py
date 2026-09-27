"""Shared fixtures for the gpx_animate test suite."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

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
def track_tiff(tmp_path_factory) -> Path:
    """A small GeoTIFF covering the fixture track, in Web Mercator.

    The track sits at 7.0E 45.0N, which is about 779500, 5622500 in Web
    Mercator, and spans roughly 700 m by 2200 m. This raster is a 2 km square
    around it, so the track and its 15% margin both fall inside; the provider
    rejects a raster that does not overlap the view. Generated rather than
    committed, so the file says what it is.
    """
    left, bottom, right, top = 778900.0, 5621000.0, 780900.0, 5625000.0
    size = 64
    path = tmp_path_factory.mktemp("tiff") / "track.tif"
    # A diagonal gradient, so a mis-oriented render shows up as a flipped map.
    ramp = np.tile(np.linspace(0, 255, size, dtype="uint8"), (size, 1))
    pixels = np.stack([ramp, ramp.T, np.full((size, size), 40, dtype="uint8")])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_bounds(left, bottom, right, top, size, size),
    ) as dst:
        dst.write(pixels)
    return path


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
