"""The shipped defaults module."""

from gpx_animate.config.defaults import DEFAULT_BASEMAP_STYLE
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
from gpx_animate.domain.render_config import SIZE_PRESETS
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import DEFAULT_STYLE


class TestSizes:
    def test_exposes_every_preset(self):
        assert set(SIZES) == {"16:9", "1:1", "9:16"}

    def test_is_the_domain_table_not_a_copy(self):
        """One source of truth: renaming a preset cannot desync the two."""
        assert SIZES is SIZE_PRESETS

    def test_values_are_width_height_in_inches(self):
        assert SIZES["1:1"] == (9.0, 9.0)
        assert SIZES["16:9"][0] > SIZES["16:9"][1]
        assert SIZES["9:16"][1] > SIZES["9:16"][0]


class TestDefaultConfig:
    def test_uses_the_shipped_basemap(self):
        assert DEFAULT_BASEMAP_STYLE == "topo"
        assert default_config().style == DEFAULT_BASEMAP_STYLE

    def test_matches_the_render_config_defaults(self):
        assert default_config() == RenderConfig(style=DEFAULT_BASEMAP_STYLE)

    def test_carries_the_default_appearance(self):
        assert default_config().appearance == DEFAULT_STYLE

    def test_returns_a_fresh_object_each_time(self):
        """Two runs must not be able to see each other's overrides."""
        first = default_config()
        second = default_config()
        assert first == second
        assert first is not second

    def test_leaves_no_output_path(self, short_track_gpx):
        """The CLI decides where output goes; defaults do not guess."""
        assert default_config().out is None
        assert short_track_gpx.exists()
