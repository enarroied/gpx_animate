"""Which provider a config asks for: one line of precedence, one place."""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from gpx_animate.adapters.basemaps.factory import NONE_STYLE
from gpx_animate.adapters.basemaps.factory import build_basemap
from gpx_animate.adapters.basemaps.factory import build_elevation
from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.basemaps.hillshade import HillshadeBasemap
from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.elevation.copernicus import CopernicusDem
from gpx_animate.adapters.elevation.local import LocalDem
from gpx_animate.application.errors import BasemapError
from gpx_animate.application.errors import DemNotReadableError
from gpx_animate.application.errors import TiffNotReadableError
from gpx_animate.domain.render_config import DEFAULT_STYLE
from gpx_animate.domain.render_config import RenderConfig


def _write_dem(path: Path) -> Path:
    """Write a tiny single-band GeoTIFF so LocalDem can open it.

    Args:
        path: Where to write.

    Returns:
        The path written.
    """
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(0.0, 0.0, 1.0, 1.0, width=2, height=2),
    ) as dst:
        dst.write(np.zeros((2, 2), dtype="float32"), 1)
    return path


class TestStyleChoices:
    def test_includes_every_tile_style(self):
        assert set(available_styles()) <= set(style_choices())

    def test_includes_none(self):
        assert NONE_STYLE in style_choices()

    def test_has_no_duplicates(self):
        assert len(style_choices()) == len(set(style_choices()))


class TestBuildBasemap:
    def test_a_tile_style_builds_a_tile_provider(self):
        assert isinstance(build_basemap(RenderConfig(style="osm")), TileBasemap)

    def test_none_builds_a_solid_colour(self):
        assert isinstance(build_basemap(RenderConfig(style="none")), BlankBasemap)

    def test_none_passes_the_configured_background_along(self):
        """The factory keeps wiring it up even though the provider ignores it.

        ``BlankBasemap`` draws nothing and lets the renderer paint
        ``appearance.bg_color`` onto the axes, so this argument is not what
        makes the background dark. It is pinned because a ``--style none``
        render still has to be built the same way as every other, and
        ``test_a_none_style_render_is_the_configured_background`` is the test
        that the colour actually reaches the frame.
        """
        appearance = dataclasses.replace(DEFAULT_STYLE, bg_color="#101010")
        config = RenderConfig(style="none", appearance=appearance)
        provider = build_basemap(config)
        assert isinstance(provider, BlankBasemap)
        assert provider.color == "#101010"

    def test_a_tiff_wins_over_a_tile_style(self, tmp_path):
        """Bringing your own imagery leaves no tile server to choose."""
        config = RenderConfig(style="osm", tiff=tmp_path / "missing.tif")
        with pytest.raises(TiffNotReadableError, match="no such GeoTIFF"):
            build_basemap(config)

    def test_a_tiff_wins_over_none(self, tmp_path):
        config = RenderConfig(style="none", tiff=tmp_path / "missing.tif")
        with pytest.raises(TiffNotReadableError, match="no such GeoTIFF"):
            build_basemap(config)

    def test_an_unknown_style_is_a_clear_error(self):
        """A config file can name a style argparse would have rejected."""
        with pytest.raises(BasemapError, match="unknown basemap style 'nope'"):
            build_basemap(RenderConfig(style="nope"))


class TestBuildElevation:
    def test_auto_builds_the_copernicus_provider(self):
        assert isinstance(build_elevation("auto"), CopernicusDem)

    def test_a_path_builds_the_local_provider(self, tmp_path):
        path = tmp_path / "dem.tif"
        _write_dem(path)
        assert isinstance(build_elevation(str(path)), LocalDem)

    def test_a_missing_local_path_is_rejected(self, tmp_path):
        with pytest.raises(DemNotReadableError, match="does not exist"):
            build_elevation(str(tmp_path / "nope.tif"))


class TestTheDemComposition:
    def test_a_dem_wraps_the_underlay_in_a_hillshade(self):
        config = RenderConfig(style="none", dem="auto")
        provider = build_basemap(config)
        assert isinstance(provider, HillshadeBasemap)
        assert isinstance(provider.underlay, BlankBasemap)
        assert isinstance(provider.elevation, CopernicusDem)

    def test_a_dem_over_a_tile_style_wraps_the_tiles(self):
        config = RenderConfig(style="osm", dem="auto")
        provider = build_basemap(config)
        assert isinstance(provider, HillshadeBasemap)
        assert isinstance(provider.underlay, TileBasemap)

    def test_no_dem_leaves_the_underlay_alone(self):
        assert isinstance(build_basemap(RenderConfig(style="osm")), TileBasemap)

    def test_the_hillshade_knobs_reach_the_provider(self):
        config = RenderConfig(
            style="none",
            dem="auto",
            hillshade_azimuth=90.0,
            hillshade_altitude=30.0,
            hillshade_z=2.0,
            hillshade_strength=0.5,
        )
        provider = build_basemap(config)
        assert isinstance(provider, HillshadeBasemap)
        assert provider.azimuth == 90.0
        assert provider.altitude == 30.0
        assert provider.z_factor == 2.0
        assert provider.strength == 0.5

    def test_dem_and_tiff_together_never_reach_the_factory(self, tmp_path):
        """The config rejects the combination before the factory is asked."""
        with pytest.raises(ValueError, match="one or the other"):
            RenderConfig(tiff=tmp_path / "map.tif", dem="auto")
