"""Stacking the layers: precedence, coercion, and the errors in between."""

from pathlib import Path

from pytest import mark
from pytest import raises

from gpx_animate.config.defaults import default_config
from gpx_animate.config.layers import ConfigError
from gpx_animate.config.loader import apply_overrides
from gpx_animate.config.loader import coerce_overrides
from gpx_animate.config.loader import load_config
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.style import Style


def load(tmp_path, environ=None, user_toml=None, project_toml=None):
    """Resolve the layers against a temporary home and project directory."""
    user_path = tmp_path / "user.toml"
    if user_toml is not None:
        user_path.write_text(user_toml)
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    if project_toml is not None:
        (project_dir / "gpx-animate.toml").write_text(project_toml)
    return load_config(project_dir, environ or {}, user_path=user_path)


class TestDefaults:
    def test_no_files_and_no_environment_means_the_defaults(self, tmp_path):
        assert load(tmp_path) == default_config()

    def test_a_missing_project_directory_is_not_an_error(self, tmp_path):
        config = load_config(tmp_path / "nowhere", {}, user_path=tmp_path / "no.toml")
        assert config == default_config()


class TestPrecedence:
    def test_the_project_file_beats_the_user_file(self, tmp_path):
        config = load(
            tmp_path,
            user_toml='style = "osm"',
            project_toml='style = "satellite"',
        )
        assert config.style == "satellite"

    def test_the_environment_beats_both_files(self, tmp_path):
        config = load(
            tmp_path,
            environ={"GPX_ANIMATE_STYLE": "topo"},
            user_toml='style = "osm"',
            project_toml='style = "satellite"',
        )
        assert config.style == "topo"

    def test_a_key_set_in_only_the_lower_layer_survives(self, tmp_path):
        config = load(tmp_path, project_toml="dpi = 300")
        assert config.dpi == 300
        assert config.style == default_config().style

    def test_the_appearance_group_merges_rather_than_replaces(self, tmp_path):
        config = load(tmp_path, project_toml="[appearance]\nfont = 'Inter'\n")
        assert config.appearance.font == "Inter"
        assert config.appearance.bg_color == Style().bg_color


class TestCoercion:
    @mark.parametrize(
        ("key", "raw", "expected"),
        [
            ("duration", "2.5", 2.5),
            ("duration", 2.5, 2.5),
            ("hold", "1", 1.0),
            ("margin", "0.2", 0.2),
            ("fps", "24", 24),
            ("dpi", 300, 300),
            ("output_dir", "renders", Path("renders")),
            ("out", "a/b.mp4", Path("a/b.mp4")),
            ("logo_start", "brand.png", "brand.png"),
            ("logo_end", "car", "car"),
            ("logo_size_px", "192", 192),
            ("logo_size_px", 192, 192),
            ("force", "yes", True),
            ("force", "off", False),
            ("force", True, True),
            ("style", "osm", "osm"),
            ("bounds", "2.35,48.85,2.40,48.90", Bbox(2.35, 48.85, 2.40, 48.90)),
            ("bounds", Bbox(1.0, 2.0, 3.0, 4.0), Bbox(1.0, 2.0, 3.0, 4.0)),
        ],
    )
    def test_each_type_is_converted(self, key, raw, expected):
        assert coerce_overrides({key: raw}, origin="test")[key] == expected

    @mark.parametrize("word", ["1", "true", "TRUE", "yes", "on"])
    def test_boolean_spellings_that_are_true(self, word):
        assert coerce_overrides({"force": word}, origin="test")["force"] is True

    @mark.parametrize("word", ["0", "false", "no", "off"])
    def test_boolean_spellings_that_are_false(self, word):
        assert coerce_overrides({"force": word}, origin="test")["force"] is False

    def test_a_blank_optional_path_means_unset(self):
        assert coerce_overrides({"out": "  "}, origin="test")["out"] is None

    def test_a_logo_source_is_left_as_a_string(self):
        """A source may be a registry name, so it survives Path-free."""
        assert (
            coerce_overrides({"logo_start": "~/x.png"}, origin="test")["logo_start"]
            == "~/x.png"
        )

    def test_a_word_where_a_number_belongs_names_the_key(self):
        with raises(ConfigError) as caught:
            coerce_overrides({"fps": "many"}, origin="gpx-animate.toml")
        message = str(caught.value)
        assert "gpx-animate.toml" in message
        assert "fps" in message

    def test_a_nonsense_boolean_says_what_is_allowed(self):
        with raises(ConfigError, match="not a boolean"):
            coerce_overrides({"force": "maybe"}, origin="test")

    def test_a_float_where_an_int_belongs_is_rejected(self):
        """Silently truncating 29.97 fps to 29 would be a nasty surprise."""
        with raises(ConfigError, match="fps"):
            coerce_overrides({"fps": "29.97"}, origin="test")

    def test_a_bad_bounds_string_names_the_layer(self):
        with raises(ConfigError, match="min_lon,min_lat,max_lon,max_lat"):
            coerce_overrides({"bounds": "1,2,3"}, origin="~/config.toml")

    def test_a_reversed_bounds_box_is_rejected_here_too(self):
        """The coercer returns a box, so the config's own check would also fire;
        but the ConfigError wrapping happens here, naming the source."""
        with raises(ConfigError, match="min < max"):
            coerce_overrides({"bounds": "2.40,48.85,2.35,48.90"}, origin="test")


class TestApplyOverrides:
    def test_replaces_a_single_field(self):
        config = apply_overrides(default_config(), {"fps": 24})
        assert config.fps == 24
        assert config.style == default_config().style

    def test_leaves_the_base_untouched(self):
        base = default_config()
        apply_overrides(base, {"fps": 24})
        assert base.fps == 30

    def test_folds_the_appearance_group_into_a_new_style(self):
        config = apply_overrides(default_config(), {"appearance.font": "Inter"})
        assert config.appearance.font == "Inter"
        assert config.appearance.title_color == Style().title_color

    def test_reruns_validation(self):
        """dataclasses.replace is what keeps a bad layer from slipping through."""
        with raises(ValueError, match="fps must be > 0"):
            apply_overrides(default_config(), {"fps": 0})

    def test_rejects_an_unknown_size(self):
        with raises(ValueError, match="size must be one of"):
            apply_overrides(default_config(), {"size": "4:3"})

    def test_an_unflattened_group_is_refused_rather_than_swallowed(self):
        """A nested table here would replace the Style with a dict."""
        with raises(ConfigError, match="appearance.font"):
            apply_overrides(default_config(), {"appearance": {"font": "Inter"}})


class TestErrorsReachTheUser:
    def test_a_broken_project_file_names_itself(self, tmp_path):
        with raises(ConfigError, match="gpx-animate.toml is not valid TOML"):
            load(tmp_path, project_toml="duration = \n")

    def test_a_typo_in_a_file_is_rejected(self, tmp_path):
        with raises(ConfigError, match="durtaion"):
            load(tmp_path, project_toml="durtaion = 2.0")

    def test_a_stray_environment_variable_is_rejected(self, tmp_path):
        with raises(ConfigError, match="the environment"):
            load(tmp_path, environ={"GPX_ANIMATE_NOPE": "1"})

    def test_an_out_of_range_value_is_rejected(self, tmp_path):
        with raises(ValueError, match="duration must be > 0"):
            load(tmp_path, environ={"GPX_ANIMATE_DURATION": "-1"})


class TestTiff:
    """The TIFF key has to be settable in every layer like any other (US-6)."""

    def test_it_comes_from_a_project_file(self, tmp_path):
        config = load(tmp_path, project_toml='tiff = "map.tif"')
        assert config.tiff == Path("map.tif")

    def test_it_comes_from_the_environment(self, tmp_path):
        config = load(tmp_path, environ={"GPX_ANIMATE_TIFF": "map.tif"})
        assert config.tiff == Path("map.tif")

    def test_it_defaults_to_unset(self, tmp_path):
        assert load(tmp_path).tiff is None

    def test_a_blank_one_means_unset(self):
        assert coerce_overrides({"tiff": "  "}, origin="test")["tiff"] is None

    def test_a_home_relative_one_is_expanded(self):
        assert coerce_overrides({"tiff": "~/map.tif"}, origin="test")["tiff"] == (
            Path.home() / "map.tif"
        )

    def test_style_none_survives_the_file(self, tmp_path):
        assert load(tmp_path, project_toml='style = "none"').style == "none"


class TestReadsTheRealEnvironment:
    def test_defaults_to_the_process_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GPX_ANIMATE_HOLD", "0.5")
        config = load_config(tmp_path, user_path=tmp_path / "no.toml")
        assert config.hold == 0.5

    def test_the_process_environment_is_optional(self, tmp_path, monkeypatch):
        """Passing an empty mapping must mean "no env layer", not "the real one"."""
        monkeypatch.setenv("GPX_ANIMATE_HOLD", "0.5")
        config = load_config(tmp_path, {}, user_path=tmp_path / "no.toml")
        assert config.hold == default_config().hold
