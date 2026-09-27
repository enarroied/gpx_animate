"""Reading a config layer: TOML files and GPX_ANIMATE_* variables."""

from pytest import mark
from pytest import raises

from gpx_animate.config import layers
from gpx_animate.config.layers import APPEARANCE_GROUP
from gpx_animate.config.layers import ConfigError
from gpx_animate.config.layers import config_keys
from gpx_animate.config.layers import env_key_map
from gpx_animate.config.layers import flatten_toml
from gpx_animate.config.layers import read_env_layer
from gpx_animate.config.layers import read_toml_layer
from gpx_animate.config.layers import settable_keys
from gpx_animate.config.layers import user_config_path
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import Style


class TestKeys:
    def test_lists_every_render_config_field(self):
        keys = config_keys()
        for field in ("style", "duration", "fps", "output_dir", "force", "out"):
            assert field in keys

    def test_lists_the_style_fields_as_a_nested_group(self):
        """SPECS section 5: nested groups are TOML tables and env sub-keys."""
        assert "appearance.font" in config_keys()
        assert "appearance.track_bright" in config_keys()

    def test_is_derived_from_the_dataclasses(self):
        """A new domain field is settable everywhere without editing a list."""
        assert len(config_keys()) == len(RenderConfig.__dataclass_fields__) + len(
            Style.__dataclass_fields__
        )

    def test_env_names_replace_the_dot_with_an_underscore(self):
        mapping = env_key_map()
        assert mapping["APPEARANCE_BG_COLOR"] == "appearance.bg_color"
        assert mapping["LOGO_POSITION"] == "logo_position"

    def test_env_names_do_not_collide(self):
        """LOGO and LOGO_POSITION share a prefix but must stay distinct keys."""
        mapping = env_key_map()
        assert mapping["LOGO"] == "logo"
        assert mapping["LOGO_POSITION"] == "logo_position"
        assert len(mapping) == len(settable_keys())

    def test_the_group_name_is_not_settable_on_its_own(self):
        """GPX_ANIMATE_APPEARANCE would replace the whole Style with a string."""
        assert APPEARANCE_GROUP not in settable_keys()
        assert "APPEARANCE" not in env_key_map()


class TestUserConfigPath:
    def test_lives_under_dot_config(self, monkeypatch, tmp_path):
        monkeypatch.setattr(layers.Path, "home", classmethod(lambda cls: tmp_path))
        assert user_config_path() == tmp_path / ".config/gpx-animate/config.toml"


class TestReadTomlLayer:
    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert read_toml_layer(tmp_path / "nope.toml") == {}

    def test_reads_top_level_keys(self, tmp_path):
        path = tmp_path / "gpx-animate.toml"
        path.write_text('duration = 2.5\nstyle = "osm"\n')
        assert read_toml_layer(path) == {"duration": 2.5, "style": "osm"}

    def test_reads_nested_tables(self, tmp_path):
        path = tmp_path / "gpx-animate.toml"
        path.write_text("[appearance]\nfont = 'Inter'\n")
        assert read_toml_layer(path) == {"appearance": {"font": "Inter"}}

    def test_reports_invalid_toml_with_the_path(self, tmp_path):
        path = tmp_path / "gpx-animate.toml"
        path.write_text("duration = \n")
        with raises(ConfigError, match="gpx-animate.toml is not valid TOML"):
            read_toml_layer(path)

    def test_reports_an_unreadable_path(self, tmp_path):
        """A directory where the file should be: not a crash, just a message."""
        path = tmp_path / "config.toml"
        path.mkdir()
        with raises(ConfigError, match="cannot read"):
            read_toml_layer(path)


class TestFlattenToml:
    def test_keeps_top_level_keys_as_is(self):
        flat = flatten_toml({"fps": 24}, origin="test")
        assert flat == {"fps": 24}

    def test_flattens_the_appearance_group(self):
        flat = flatten_toml({"appearance": {"font": "Inter"}}, origin="test")
        assert flat == {"appearance.font": "Inter"}

    def test_rejects_an_unknown_key_and_lists_the_valid_ones(self):
        with raises(ConfigError) as caught:
            flatten_toml({"durtaion": 2.0}, origin="gpx-animate.toml")
        message = str(caught.value)
        assert "gpx-animate.toml" in message
        assert "'durtaion'" in message
        assert "duration" in message

    def test_the_listing_omits_the_group_header(self):
        """`appearance` is a table in TOML, so listing it as a key misleads."""
        with raises(ConfigError) as caught:
            flatten_toml({"nope": 1}, origin="test")
        listed = str(caught.value).split("valid keys are ")[1]
        listed_keys = [item.strip() for item in listed.split(",")]
        assert "appearance" not in listed_keys
        assert "appearance.font" in listed_keys

    def test_rejects_an_unknown_key_inside_the_group(self):
        with raises(ConfigError, match="appearance.fontt"):
            flatten_toml({"appearance": {"fontt": "Inter"}}, origin="test")

    def test_rejects_a_group_that_is_not_a_table(self):
        with raises(ConfigError, match=r"\[appearance\] must be a table"):
            flatten_toml({"appearance": "font=Inter"}, origin="test")


class TestReadEnvLayer:
    @mark.parametrize(
        ("variable", "value", "expected"),
        [
            ("GPX_ANIMATE_DURATION", "2.5", {"duration": "2.5"}),
            ("GPX_ANIMATE_LOGO_POSITION", "top-left", {"logo_position": "top-left"}),
            (
                "GPX_ANIMATE_APPEARANCE_BG_COLOR",
                "#000000",
                {"appearance.bg_color": "#000000"},
            ),
        ],
    )
    def test_maps_a_variable_to_a_dotted_key(self, variable, value, expected):
        assert read_env_layer({variable: value}) == expected

    def test_ignores_variables_outside_the_namespace(self):
        assert read_env_layer({"PATH": "/bin", "CARTO_API_KEY": "k"}) == {}

    def test_merges_several_variables(self):
        environ = {"GPX_ANIMATE_FPS": "24", "GPX_ANIMATE_FORCE": "yes"}
        assert read_env_layer(environ) == {"fps": "24", "force": "yes"}

    def test_rejects_a_variable_that_names_no_key(self):
        """A silently ignored typo is worse than a startup error."""
        with raises(ConfigError) as caught:
            read_env_layer({"GPX_ANIMATE_DURTAION": "2"})
        assert "the environment" in str(caught.value)
        assert "duration" in str(caught.value)

    def test_rejects_the_bare_group_variable(self):
        with raises(ConfigError, match="APPEARANCE"):
            read_env_layer({"GPX_ANIMATE_APPEARANCE": "font=Inter"})

    def test_treats_an_empty_variable_as_unset(self):
        """A shell says "unset this" with an empty value, not "set it to ''"."""
        assert read_env_layer({"GPX_ANIMATE_OUT": "  "}) == {}
