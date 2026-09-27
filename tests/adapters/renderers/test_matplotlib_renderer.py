"""Frame rendering with matplotlib, driven through fake ports."""

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeBasemap  # noqa: E402
from fakes import FakeLogoLoader  # noqa: E402

from gpx_animate.adapters.renderers.matplotlib_renderer import (
    LOGO_ANCHORS,  # noqa: E402
)
from gpx_animate.adapters.renderers.matplotlib_renderer import (  # noqa: E402
    MatplotlibRenderer,
)
from gpx_animate.application.ports import frames_are_sequential  # noqa: E402
from gpx_animate.domain.render_config import LOGO_POSITIONS  # noqa: E402
from gpx_animate.domain.render_config import RenderConfig  # noqa: E402
from gpx_animate.domain.track import Track  # noqa: E402


@pytest.fixture
def renderer():
    """A renderer wired to fakes, so no tiles are ever fetched."""
    return MatplotlibRenderer(FakeBasemap(), FakeLogoLoader())


def frames(config: RenderConfig, track: Track, tmp_path, renderer):
    """Render and return the frame paths."""
    return renderer.render(config, track, tmp_path).frame_paths


class TestFrameOutput:
    def test_writes_one_file_per_frame(self, renderer, track, tmp_path, fast_config):
        result = renderer.render(fast_config, track, tmp_path)
        assert result.frame_count == 3
        assert len(result.frame_paths) == 3
        assert all(path.exists() for path in result.frame_paths)

    def test_names_are_zero_padded_and_contiguous(self, renderer, track, tmp_path):
        config = RenderConfig(duration=0.6, hold=0.2, fps=5, dpi=20)
        result = renderer.render(config, track, tmp_path)
        assert [p.name for p in result.frame_paths] == [
            "frame_00000.png",
            "frame_00001.png",
            "frame_00002.png",
            "frame_00003.png",
        ]
        assert frames_are_sequential(result.frame_paths)

    def test_creates_the_output_directory(self, renderer, track, tmp_path):
        nested = tmp_path / "a" / "b"
        renderer.render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20), track, nested
        )
        assert nested.is_dir()

    def test_result_reports_the_directory_and_count(self, renderer, track, tmp_path):
        result = renderer.render(
            RenderConfig(duration=0.4, hold=0.2, fps=5, dpi=20), track, tmp_path
        )
        assert (result.frame_dir, result.frame_count) == (tmp_path, 3)

    def test_hold_frames_are_identical_to_the_last_draw_frame(
        self, renderer, track, tmp_path
    ):
        """Frames past n_draw_frames reuse t=1.0, so they must match pixel-wise."""
        config = RenderConfig(duration=0.6, hold=0.6, fps=5, dpi=20)
        paths = frames(config, track, tmp_path, renderer)
        final_draw = plt.imread(paths[2])
        for path in paths[3:]:
            assert np.array_equal(plt.imread(path), final_draw)

    def test_the_track_grows_across_the_draw_phase(self, renderer, track, tmp_path):
        config = RenderConfig(duration=1.0, hold=0.0, fps=5, dpi=20)
        paths = frames(config, track, tmp_path, renderer)
        assert not np.array_equal(plt.imread(paths[0]), plt.imread(paths[-1]))

    def test_output_size_follows_the_preset_and_dpi(self, renderer, track, tmp_path):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, size="9:16", dpi=20)
        path = frames(config, track, tmp_path, renderer)[0]
        assert plt.imread(path).shape[:2] == (round(12.8 * 20), round(7.2 * 20))

    def test_figure_size_helper_matches_the_rendered_pixels(
        self, renderer, track, tmp_path
    ):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, size="1:1", dpi=20)
        path = frames(config, track, tmp_path, renderer)[0]
        assert renderer.figure_size(config) == plt.imread(path).shape[1::-1]

    def test_a_single_point_track_renders(self, renderer, tmp_path):
        """Degenerate extent, but the `or 1.0` padding fallback covers it."""
        dot = Track.from_rows([(7.0, 45.0, 100.0)], name="Dot")
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20)
        assert renderer.render(config, dot, tmp_path).frame_count == 1

    def test_renders_without_a_logo_by_default(self, renderer, track, tmp_path):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20)
        assert config.logo is None
        assert renderer.render(config, track, tmp_path).frame_count == 1


class TestBasemapPort:
    def test_is_asked_for_a_basemap_once(self, track, tmp_path):
        basemap = FakeBasemap()
        MatplotlibRenderer(basemap, FakeLogoLoader()).render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20), track, tmp_path
        )
        assert len(basemap.calls) == 1

    def test_is_told_which_projection_to_use(self, track, tmp_path):
        basemap = FakeBasemap()
        MatplotlibRenderer(basemap, FakeLogoLoader()).render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20), track, tmp_path
        )
        assert basemap.calls[0]["crs"] == "EPSG:3857"

    def test_the_track_is_visible_against_the_background(
        self, renderer, track, tmp_path
    ):
        """The faint trace has to reach the pixels, not just the drawing calls."""
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=60)
        path = frames(config, track, tmp_path, renderer)[0]
        pixels = plt.imread(path)[..., :3]
        faint = np.array([0xB8, 0xB8, 0xB8]) / 255
        background = np.array([0xF5, 0xF5, 0xF2]) / 255
        # Some pixel is closer to the trace colour than to the background.
        assert (
            np.linalg.norm(pixels - faint, axis=-1)
            < np.linalg.norm(pixels - background, axis=-1)
        ).any()


class TestLogoPort:
    @pytest.mark.parametrize("position", LOGO_POSITIONS)
    def test_every_position_renders(self, track, tmp_path, logo_png, position):
        config = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            dpi=30,
            logo=logo_png,
            logo_position=position,
        )
        logos = FakeLogoLoader()
        result = MatplotlibRenderer(FakeBasemap(), logos).render(
            config, track, tmp_path
        )
        assert result.frame_count == 1
        assert logos.calls == [str(logo_png)]

    @pytest.mark.parametrize(
        ("position", "ha", "va"),
        [
            ("bottom-right", "right", "bottom"),
            ("bottom-left", "left", "bottom"),
            ("top-right", "right", "top"),
            ("top-left", "left", "top"),
        ],
    )
    def test_each_anchor_matches_its_corner(self, position, ha, va):
        """A right-anchored logo extends leftwards; the extent depends on it."""
        x, y, h_align, v_align = LOGO_ANCHORS[position]
        assert (h_align, v_align) == (ha, va)
        assert x == (0.98 if ha == "right" else 0.02)
        assert y == (0.05 if va == "bottom" else 0.95)

    def test_the_logo_loader_is_not_called_without_a_logo(
        self, track, tmp_path, renderer
    ):
        logos = FakeLogoLoader()
        MatplotlibRenderer(FakeBasemap(), logos).render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20), track, tmp_path
        )
        assert logos.calls == []

    def test_a_logo_changes_the_pixels(self, track, tmp_path, logo_png):
        """An opaque logo must actually appear; a transparent one would not."""
        plain = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=30)
        with_logo = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            dpi=30,
            logo=logo_png,
            logo_position="bottom-right",
        )
        first = (
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader())
            .render(plain, track, tmp_path / "a")
            .frame_paths[0]
        )
        second = (
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader())
            .render(with_logo, track, tmp_path / "b")
            .frame_paths[0]
        )
        assert not np.array_equal(plt.imread(first), plt.imread(second))

    def test_a_transparent_logo_draws_nothing(self, track, tmp_path):
        """Alpha 0 is invisible, so such a render matches the no-logo one.

        The fixture logo has visible pixels as well as transparency, which is
        what makes the test above meaningful.
        """
        plain = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=30)
        invisible = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            dpi=30,
            logo=tmp_path / "nothing.png",
            logo_position="bottom-right",
        )
        first = (
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader())
            .render(plain, track, tmp_path / "a")
            .frame_paths[0]
        )
        second = (
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader(np.zeros((4, 4, 4))))
            .render(invisible, track, tmp_path / "b")
            .frame_paths[0]
        )
        assert np.array_equal(plt.imread(first), plt.imread(second))


class TestHud:
    def test_the_hud_reports_the_track_totals(self, renderer, tmp_path):
        """The HUD is the only place the totals appear, so it must be drawn.

        Two tracks with very different totals have to produce different pixels
        at the same frame index; otherwise the text is not being rendered.
        """
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=30)
        short = Track.from_rows([(7.0, 45.0, 100.0), (7.001, 45.0, 100.0)], name="T")
        long = Track.from_rows([(7.0, 45.0, 100.0), (7.5, 45.4, 900.0)], name="T")
        first = frames(config, short, tmp_path / "a", renderer)[0]
        second = frames(config, long, tmp_path / "b", renderer)[0]
        assert not np.array_equal(plt.imread(first), plt.imread(second))
