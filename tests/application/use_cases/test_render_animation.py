"""The render_animation use case, driven through a fake renderer port.

SPECS US-3: with a fake renderer port, assert the correct number of frames and
that the last N are held. US-5: the logo sources are resolved up front, so a
missing logo fails before the renderer is even asked to draw.
"""

from fakes import FakeLogoLoader
from fakes import FakeRenderer
from pytest import raises

from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.application.errors import LogoFileNotFoundError
from gpx_animate.application.errors import UnknownLogoError
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


class TestLogoSources:
    def test_no_logos_means_nothing_is_resolved(self, track, tmp_path):
        logos = FakeLogoLoader()
        render_animation(
            RenderConfig(duration=0.2, hold=0.0, fps=5),
            track,
            tmp_path,
            FakeRenderer(),
            logos,
        )
        assert logos.calls == []

    def test_every_requested_source_is_resolved_before_rendering(self, track, tmp_path):
        config = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            logo_start="a",
            logo_end="b",
            logo_marker="c",
        )
        logos = FakeLogoLoader()
        renderer = FakeRenderer()
        render_animation(config, track, tmp_path, renderer, logos)
        assert sorted(logos.calls) == ["a", "b", "c"]
        assert len(renderer.calls) == 1

    def test_a_bad_source_raises_and_never_renders(self, track, tmp_path, monkeypatch):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, logo_start="missing")

        class Exploding(FakeLogoLoader):
            def resolve(self, source):  # noqa: D102
                raise UnknownLogoError(f"{source} is unknown")

        with raises(UnknownLogoError, match="missing"):
            render_animation(config, track, tmp_path, FakeRenderer(), Exploding())
        assert len(FakeRenderer().calls) == 0

    def test_a_missing_file_is_reported_not_a_traceback(
        self, track, tmp_path, logo_png
    ):
        """:exc:`LogoFileNotFoundError` is deliberate, and gets a message."""

        class Missing(PngLogoLoader):
            def resolve(self, source):  # noqa: D102
                raise LogoFileNotFoundError(f"logo file {source!r} does not exist")

        config = RenderConfig(duration=0.2, hold=0.0, fps=5, logo_start="car")
        with raises(LogoFileNotFoundError):
            render_animation(config, track, tmp_path, FakeRenderer(), Missing())

    def test_without_a_loader_nothing_is_validated(self, track, tmp_path):
        """No logos port, no pre-flight: the renderer would catch it or not."""
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, logo_start="nope")
        renderer = FakeRenderer()
        render_animation(config, track, tmp_path, renderer)
        assert len(renderer.calls) == 1
