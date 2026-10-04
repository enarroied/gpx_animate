"""The standalone elevation chart video, and its lockstep with the map video."""

import dataclasses

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeBasemap  # noqa: E402
from fakes import FakeLogoLoader  # noqa: E402

from gpx_animate.adapters.renderers import (
    matplotlib_renderer as map_renderer,  # noqa: E402
)
from gpx_animate.adapters.renderers import (
    profile_renderer as profile_renderer_module,  # noqa: E402, E501
)
from gpx_animate.adapters.renderers.elevation_chart import (  # noqa: E402
    revealed_point_count,
)
from gpx_animate.adapters.renderers.matplotlib_renderer import (  # noqa: E402
    MatplotlibRenderer,
)
from gpx_animate.adapters.renderers.profile_renderer import (  # noqa: E402
    ProfileRenderer,
)
from gpx_animate.application.ports import FrameRenderer  # noqa: E402
from gpx_animate.application.ports import RenderResult  # noqa: E402
from gpx_animate.domain.render_config import RenderConfig  # noqa: E402


@pytest.fixture
def renderer():
    """The standalone renderer. It needs no ports, which is the point."""
    return ProfileRenderer()


@pytest.fixture
def chart_config():
    """A fast config whose frame count is small but not degenerate."""
    return RenderConfig(duration=0.6, hold=0.2, fps=5, size="1:1", dpi=20)


class TestPortConformance:
    def test_it_satisfies_the_frame_renderer_port(self, renderer):
        assert isinstance(renderer, FrameRenderer)


class TestFrameOutput:
    def test_it_writes_one_file_per_frame(
        self, renderer, chart_config, track, tmp_path
    ):
        result = renderer.render(chart_config, track, tmp_path)
        assert result.frame_count == chart_config.n_frames
        assert len(result.frame_paths) == chart_config.n_frames
        assert all(path.exists() for path in result.frame_paths)

    def test_frames_are_numbered_from_zero(
        self, renderer, chart_config, track, tmp_path
    ):
        """The ffmpeg encoder globs frame_%05d.png, so the naming is load-bearing."""
        result = renderer.render(chart_config, track, tmp_path)
        assert result.frame_paths[0].name == "frame_00000.png"
        assert result.frame_paths[-1].name.endswith(".png")

    def test_it_reports_the_directory_it_wrote_into(
        self, renderer, chart_config, track, tmp_path
    ):
        out = tmp_path / "frames"
        result = renderer.render(chart_config, track, out)
        assert result.frame_dir == out

    def test_it_creates_a_missing_directory(
        self, renderer, chart_config, track, tmp_path
    ):
        out = tmp_path / "deep" / "frames"
        renderer.render(chart_config, track, out)
        assert out.is_dir()

    def test_it_reuses_an_existing_directory(
        self, renderer, chart_config, track, tmp_path
    ):
        out = tmp_path / "frames"
        out.mkdir()
        result = renderer.render(chart_config, track, out)
        assert result.frame_count == chart_config.n_frames

    def test_the_frames_are_not_blank(self, renderer, chart_config, track, tmp_path):
        """A chart that rendered nothing would still produce valid PNGs."""
        result = renderer.render(chart_config, track, tmp_path)
        image = plt.imread(result.frame_paths[-1])
        assert float(image[..., :3].std()) > 0.0


class TestFrameLock:
    """US-11 requires the two videos to be alignable, so they share progress."""

    def test_it_uses_the_shared_progress_helper(self, monkeypatch, track, tmp_path):
        seen = []
        real = revealed_point_count

        def spy(index, n_draw_frames, n_total):
            seen.append(index)
            return real(index, n_draw_frames, n_total)

        monkeypatch.setattr(
            "gpx_animate.adapters.renderers.profile_renderer.revealed_point_count", spy
        )
        config = RenderConfig(duration=0.6, hold=0.2, fps=5, size="1:1", dpi=20)
        ProfileRenderer().render(config, track, tmp_path)
        assert seen == list(range(config.n_frames))

    def test_the_map_renderer_uses_the_same_helper(self, monkeypatch, track, tmp_path):
        seen = []
        real = revealed_point_count

        def spy(index, n_draw_frames, n_total):
            seen.append(index)
            return real(index, n_draw_frames, n_total)

        monkeypatch.setattr(
            "gpx_animate.adapters.renderers.matplotlib_renderer.revealed_point_count",
            spy,
        )
        config = RenderConfig(duration=0.6, hold=0.2, fps=5, size="1:1", dpi=20)
        MatplotlibRenderer(FakeBasemap(), FakeLogoLoader()).render(
            config, track, tmp_path
        )
        assert seen == list(range(config.n_frames))

    def test_both_videos_have_the_same_frame_count(self, track, tmp_path, chart_config):
        chart = ProfileRenderer().render(chart_config, track, tmp_path / "chart")
        map_result = MatplotlibRenderer(FakeBasemap(), FakeLogoLoader()).render(
            chart_config, track, tmp_path / "map"
        )
        assert chart.frame_count == map_result.frame_count
        assert chart.frame_count == chart_config.n_frames

    def test_both_renderers_bind_the_one_shared_helper(self):
        """The lockstep guarantee, structurally.

        If either module grew its own progress arithmetic this would still pass
        the frame-count tests and quietly break the alignment, so pin the shared
        object itself rather than its behaviour.
        """
        assert (
            map_renderer.revealed_point_count
            is profile_renderer_module.revealed_point_count
        )
        assert map_renderer.revealed_point_count is revealed_point_count

    def test_the_shared_helper_clamps_to_the_track(self, track):
        """Both renderers index by the returned count, so it must stay in range."""
        n_total = len(track.points)
        for index in range(30):
            count = revealed_point_count(index, 7, n_total)
            assert 2 <= count <= n_total

    def test_the_hold_frames_are_identical(
        self, renderer, chart_config, track, tmp_path
    ):
        """A hold frame reuses the final state, so the pixels must match."""
        result = renderer.render(chart_config, track, tmp_path)
        last_draw = plt.imread(result.frame_paths[chart_config.n_draw_frames - 1])
        first_hold = plt.imread(result.frame_paths[chart_config.n_draw_frames])
        assert (last_draw == first_hold).all()


class TestNoDecoration:
    def test_it_takes_no_basemap_port(self):
        """A chart video is the chart alone; tiles would make it a second map."""
        assert "basemap" not in ProfileRenderer.render.__code__.co_varnames

    def test_it_takes_no_logo_port(self):
        assert "logos" not in ProfileRenderer.render.__code__.co_varnames

    def test_its_constructor_takes_no_arguments(self):
        assert ProfileRenderer.__init__ is object.__init__


class TestConfigCoupling:
    def test_it_reuses_the_main_size(self, track, tmp_path):
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, size="1:1", dpi=20, margin=0.15
        )
        result = ProfileRenderer().render(config, track, tmp_path)
        width, height = config.size_inches
        image = plt.imread(result.frame_paths[0])
        assert image.shape[1] == int(width * config.dpi)
        assert image.shape[0] == int(height * config.dpi)

    def test_a_portrait_preset_gives_a_portrait_chart(self, track, tmp_path):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, size="9:16", dpi=20)
        result = ProfileRenderer().render(config, track, tmp_path)
        image = plt.imread(result.frame_paths[0])
        assert image.shape[0] > image.shape[1]

    def test_the_overlay_setting_does_not_change_the_chart_video(self, track, tmp_path):
        """--profile is the overlay's business; this video is always full frame."""
        off = RenderConfig(duration=0.2, hold=0.0, fps=5, size="1:1", dpi=20)
        corner = dataclasses.replace(off, profile="bottom-left")
        a = ProfileRenderer().render(off, track, tmp_path / "a")
        b = ProfileRenderer().render(corner, track, tmp_path / "b")
        assert plt.imread(a.frame_paths[0]).shape == plt.imread(b.frame_paths[0]).shape

    def test_it_is_an_ordinary_render_config(self, track, tmp_path):
        """chart_video is a separate switch, so it needs no field here."""
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, size="1:1", dpi=20, chart_video=True
        )
        result = ProfileRenderer().render(config, track, tmp_path)
        assert isinstance(result, RenderResult)
