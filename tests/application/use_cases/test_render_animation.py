"""The render_animation use case, driven through a fake renderer port.

SPECS US-3: with a fake renderer port, assert the correct number of frames and
that the last N are held.
"""

from fakes import FakeRenderer
from pytest import raises

from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Point
from gpx_animate.domain.track import Track


class TestWiring:
    def test_passes_the_config_track_and_directory_through(self, track, tmp_path):
        renderer = FakeRenderer()
        config = RenderConfig(duration=0.4, hold=0.2, fps=5)
        render_animation(config, track, tmp_path, renderer)
        assert renderer.calls == [(config, track, tmp_path)]

    def test_returns_a_result_pointing_at_the_directory(self, track, tmp_path):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5)
        result = render_animation(config, track, tmp_path, FakeRenderer())
        assert result.frame_dir == tmp_path


class TestFrameCounts:
    def test_reports_the_frame_count_from_the_config(self, track, tmp_path):
        """3 draw + 1 hold. The count comes from RenderConfig, not the renderer."""
        config = RenderConfig(duration=0.6, hold=0.2, fps=5)
        result = render_animation(config, track, tmp_path, FakeRenderer())
        assert result.frame_count == 4

    def test_the_trailing_frames_are_the_held_ones(self, track, tmp_path):
        """Frames from n_draw_frames onwards are the hold, frozen on the last state."""
        config = RenderConfig(duration=0.6, hold=0.6, fps=5)
        result = render_animation(config, track, tmp_path, FakeRenderer())
        assert result.frame_count == 6
        assert config.n_draw_frames == 3
        assert config.n_hold_frames == 3
        assert [p.name for p in result.frame_paths[3:]] == [
            "frame_00003.png",
            "frame_00004.png",
            "frame_00005.png",
        ]

    def test_no_hold_means_no_held_frames(self, track, tmp_path):
        config = RenderConfig(duration=0.6, hold=0.0, fps=5)
        result = render_animation(config, track, tmp_path, FakeRenderer())
        assert (result.frame_count, config.n_hold_frames) == (3, 0)

    def test_a_single_point_track_still_renders(self, track, tmp_path):
        """Degenerate, but it must not be rejected before the adapter sees it."""
        config = RenderConfig(duration=0.2, hold=0.0, fps=5)
        dot = Track(points=(Point(7.0, 45.0, 100.0),), name="Dot")
        result = render_animation(config, dot, tmp_path, FakeRenderer())
        assert result.frame_count == 1

    def test_an_invalid_config_never_reaches_the_renderer(self, track, tmp_path):
        with raises(ValueError, match="fps must be > 0"):
            render_animation(RenderConfig(fps=0), track, tmp_path, FakeRenderer())
