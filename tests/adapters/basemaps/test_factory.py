"""Which provider a config asks for: one line of precedence, one place."""

import dataclasses

import pytest

from gpx_animate.adapters.basemaps.factory import NONE_STYLE
from gpx_animate.adapters.basemaps.factory import build_basemap
from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.application.errors import BasemapError
from gpx_animate.application.errors import TiffNotReadableError
from gpx_animate.domain.render_config import DEFAULT_STYLE
from gpx_animate.domain.render_config import RenderConfig


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
