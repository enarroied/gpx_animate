"""RenderConfig validation and the frame arithmetic derived from it."""

from dataclasses import replace
from pathlib import Path

import pytest

from gpx_animate.config.defaults import default_config
from gpx_animate.domain.render_config import LOGO_POSITIONS
from gpx_animate.domain.render_config import SIZE_PRESETS
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import DEFAULT_STYLE
from gpx_animate.domain.style import Style


class TestValidation:
    @pytest.mark.parametrize("fps", [0, -1, -30])
    def test_fps_must_be_positive(self, fps):
        with pytest.raises(ValueError, match="fps must be > 0"):
            RenderConfig(fps=fps)

    @pytest.mark.parametrize("duration", [0, -0.5])
    def test_duration_must_be_positive(self, duration):
        with pytest.raises(ValueError, match="duration must be > 0"):
            RenderConfig(duration=duration)

    def test_hold_may_be_zero(self):
        """No hold is a legitimate choice; only negative is not."""
        assert RenderConfig(hold=0.0).n_hold_frames == 0

    def test_negative_hold_is_rejected(self):
        with pytest.raises(ValueError, match="hold must be >= 0"):
            RenderConfig(hold=-1.0)

    @pytest.mark.parametrize("dpi", [0, -150])
    def test_dpi_must_be_positive(self, dpi):
        with pytest.raises(ValueError, match="dpi must be > 0"):
            RenderConfig(dpi=dpi)

    def test_negative_margin_is_rejected(self):
        with pytest.raises(ValueError, match="margin must be >= 0"):
            RenderConfig(margin=-0.1)

    def test_unknown_size_is_rejected(self):
        with pytest.raises(ValueError, match="size must be one of"):
            RenderConfig(size="4:3")

    @pytest.mark.parametrize("size", sorted(SIZE_PRESETS))
    def test_every_preset_is_accepted(self, size):
        assert RenderConfig(size=size).size_inches == SIZE_PRESETS[size]

    def test_unknown_logo_position_is_rejected(self):
        with pytest.raises(ValueError, match="logo_position must be one of"):
            RenderConfig(logo_position="middle")

    @pytest.mark.parametrize("position", LOGO_POSITIONS)
    def test_every_logo_position_is_accepted(self, position):
        assert RenderConfig(logo_position=position).logo_position == position

    def test_is_frozen(self):
        config = RenderConfig()
        with pytest.raises(AttributeError):
            config.fps = 60  # ty: ignore[invalid-assignment]

    def test_replace_produces_a_new_validated_config(self):
        """dataclasses.replace re-runs __post_init__, so validation holds."""
        assert replace(RenderConfig(), fps=60).fps == 60
        with pytest.raises(ValueError, match="fps must be > 0"):
            replace(RenderConfig(), fps=0)


class TestFrameMath:
    def test_total_duration_is_draw_plus_hold(self):
        config = RenderConfig(duration=5.0, hold=1.0, fps=30)
        assert config.total_duration == pytest.approx(6.0)

    def test_frame_count_is_draw_plus_hold(self):
        config = RenderConfig(duration=1.0, hold=0.5, fps=4)
        assert config.n_draw_frames == 4
        assert config.n_hold_frames == 2
        assert config.n_frames == 6

    def test_truncation_can_shorten_the_clip(self):
        """int() truncates, so a sub-frame phase disappears entirely."""
        config = RenderConfig(duration=0.19, hold=0.19, fps=5)
        assert config.n_frames == 0

    def test_frames_match_the_shipped_defaults(self):
        config = default_config()
        assert (config.n_draw_frames, config.n_hold_frames) == (150, 30)
        assert config.n_frames == 180

    def test_one_draw_frame_does_not_divide_by_zero(self):
        """progress = index / max(1, n_draw - 1) relies on that max()."""
        assert RenderConfig(duration=0.2, hold=0.0, fps=5).n_frames == 1


class TestDefaults:
    def test_shipped_defaults_match_the_previous_config_dict(self):
        """The monolith's CONFIG values, so renders look identical."""
        config = default_config()
        assert config.style == "topo"
        assert (config.duration, config.hold, config.fps) == (5.0, 1.0, 30)
        assert (config.size, config.dpi, config.margin) == ("16:9", 150, 0.15)
        assert config.out is None
        assert config.logo is None
        assert config.appearance is DEFAULT_STYLE

    def test_default_appearance_is_the_previous_palette(self):
        assert DEFAULT_STYLE.bg_color == "#f5f5f2"
        assert DEFAULT_STYLE.track_faint == "#b8b8b8"
        assert DEFAULT_STYLE.track_bright == "#e63946"
        assert DEFAULT_STYLE.marker_color == "#1d3557"
        assert DEFAULT_STYLE.hud_color == "#1d3557"
        assert DEFAULT_STYLE.title_color == "#1d3557"
        assert DEFAULT_STYLE.font == "DejaVu Sans"

    def test_out_accepts_a_string_path(self):
        """Paths arrive from the CLI already parsed, but strings must not crash."""
        assert RenderConfig(out=Path("/tmp/x.mp4")).out == Path("/tmp/x.mp4")

    def test_a_custom_appearance_is_carried_through(self):
        style = Style(bg_color="#000000", font="Inter")
        assert RenderConfig(appearance=style).appearance.font == "Inter"

    def test_defaults_are_not_shared_state(self):
        """Frozen, so a run cannot leak settings into the next one."""
        first = default_config()
        second = default_config()
        assert first is not second
        assert replace(first, fps=10) != second
