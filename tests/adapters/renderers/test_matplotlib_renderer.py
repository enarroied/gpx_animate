"""Frame rendering with matplotlib, driven through fake ports."""

import dataclasses

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyproj  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeBasemap  # noqa: E402
from fakes import FakeLogoLoader  # noqa: E402

from gpx_animate.adapters.basemaps.none import BlankBasemap  # noqa: E402
from gpx_animate.adapters.renderers.matplotlib_renderer import (  # noqa: E402
    MatplotlibRenderer,
)
from gpx_animate.adapters.renderers.matplotlib_renderer import _logo_box  # noqa: E402
from gpx_animate.adapters.renderers.matplotlib_renderer import (  # noqa: E402
    _side_offsets,
)
from gpx_animate.application.ports import Logo  # noqa: E402
from gpx_animate.application.ports import frames_are_sequential  # noqa: E402
from gpx_animate.domain.bbox import Bbox  # noqa: E402
from gpx_animate.domain.logo import LOGO_ANCHORS  # noqa: E402
from gpx_animate.domain.render_config import DEFAULT_STYLE  # noqa: E402
from gpx_animate.domain.render_config import RenderConfig  # noqa: E402
from gpx_animate.domain.track import Track  # noqa: E402


VIEW = Bbox(-800000.0, -600000.0, 800000.0, 600000.0)
"""A stand-in view in Spherical Mercator, for the drawing tests."""


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
        assert (config.logo_start, config.logo_end, config.logo_marker) == (None,) * 3
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

    def test_is_asked_to_let_the_provider_choose_the_zoom(self, track, tmp_path):
        basemap = FakeBasemap()
        MatplotlibRenderer(basemap, FakeLogoLoader()).render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20), track, tmp_path
        )
        assert basemap.calls[0]["zoom"] == "auto"

    def _view_for(self, track, tmp_path, **kwargs):
        """Render and return the view the port was asked to cover."""
        basemap = FakeBasemap()
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, **kwargs)
        MatplotlibRenderer(basemap, FakeLogoLoader()).render(
            config, track, tmp_path / f"m{kwargs.get('margin')}"
        )
        return basemap.calls[0]["bbox"]

    def test_the_margin_reaches_the_provider(self, track, tmp_path):
        """The map has to reach the frame edges, so the padding is part of the ask."""
        tight = self._view_for(track, tmp_path, margin=0.0)
        padded = self._view_for(track, tmp_path, margin=0.5)
        assert padded.width > tight.width
        assert padded.height > tight.height
        assert padded.min_x < tight.min_x and padded.max_x > tight.max_x

    def test_the_provider_is_asked_for_exactly_the_padded_view(self, track, tmp_path):
        """The port is handed the final view, already padded: if the renderer
        asked for the bare track and padded the image itself, a partial raster
        would arrive at the wrong size."""
        transformer = pyproj.Transformer.from_crs(
            "EPSG:4326", "EPSG:3857", always_xy=True
        )
        xs, ys = transformer.transform(track.longitudes, track.latitudes)
        expected = Bbox(xs.min(), ys.min(), xs.max(), ys.max()).padded(0.15)
        basemap = FakeBasemap()
        MatplotlibRenderer(basemap, FakeLogoLoader()).render(
            RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, margin=0.15),
            track,
            tmp_path,
        )
        assert basemap.calls[0]["bbox"] == expected

    def test_a_degenerate_track_still_gets_a_drawable_view(self, tmp_path):
        """margin=0 is no *extra* padding; a one-unit floor keeps it drawable."""
        dot = Track.from_rows([(7.0, 45.0, 100.0)], name="Dot")
        view = self._view_for(dot, tmp_path, margin=0.0)
        assert view.width > 0 and view.height > 0

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


class TestBasemapDrawing:
    """draw_basemap is the seam between the port and the axes."""

    def test_the_image_is_drawn_onto_the_axes(self):
        basemap = FakeBasemap(image=np.full((2, 2, 3), 0, dtype=np.uint8))
        fig, ax = plt.subplots()
        try:
            MatplotlibRenderer(basemap, FakeLogoLoader()).draw_basemap(ax, VIEW)
            assert len(ax.images) == 1
            drawn = ax.images[0].get_array()
            assert drawn is not None
            assert np.array_equal(drawn, basemap.image)
        finally:
            plt.close(fig)

    def test_the_image_is_placed_at_its_own_extent(self):
        fig, ax = plt.subplots()
        try:
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader()).draw_basemap(ax, VIEW)
            assert tuple(ax.images[0].get_extent()) == VIEW.extent
        finally:
            plt.close(fig)

    def test_the_view_survives_an_image_that_covers_less(self):
        """imshow would otherwise resize the axes onto the image, and a partial
        raster would shrink the frame to whatever it happens to cover."""
        basemap = FakeBasemap(extent=(0.0, 1.0, 0.0, 1.0))
        fig, ax = plt.subplots()
        try:
            MatplotlibRenderer(basemap, FakeLogoLoader()).draw_basemap(ax, VIEW)
            assert ax.get_xlim() == pytest.approx((VIEW.min_x, VIEW.max_x))
            assert ax.get_ylim() == pytest.approx((VIEW.min_y, VIEW.max_y))
        finally:
            plt.close(fig)

    def test_a_none_style_render_is_a_flat_colour(self, track, tmp_path):
        """--style none: the frame is the background, with only the track on it."""
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, dpi=20, style="none", margin=0.15
        )
        result = MatplotlibRenderer(
            BlankBasemap(color=config.appearance.bg_color), FakeLogoLoader()
        ).render(config, track, tmp_path)
        pixels = plt.imread(result.frame_paths[0])
        background = np.array([0xF5, 0xF5, 0xF2]) / 255
        # The top-left corner is padding, so nothing has been drawn there.
        assert np.allclose(pixels[2, 2, :3], background, atol=0.02)

    def test_a_none_style_render_is_the_configured_background(self, track, tmp_path):
        """A dark background must actually come out dark.

        ``BlankBasemap`` returns a transparent block, so the colour can only
        arrive via the axes patch the renderer paints. If that stopped happening,
        ``--style none`` would quietly fall back to white behind dark track ink.
        """
        appearance = dataclasses.replace(DEFAULT_STYLE, bg_color="#101010")
        config = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            dpi=20,
            style="none",
            margin=0.15,
            appearance=appearance,
        )
        result = MatplotlibRenderer(
            BlankBasemap(color=config.appearance.bg_color), FakeLogoLoader()
        ).render(config, track, tmp_path)
        pixels = plt.imread(result.frame_paths[0])
        assert np.allclose(pixels[2, 2, :3], np.array([0x10] * 3) / 255, atol=0.02)


class TestAttribution:
    def test_a_credit_line_is_drawn(self):
        basemap = FakeBasemap(attribution="© Someone")
        fig, ax = plt.subplots()
        try:
            MatplotlibRenderer(basemap, FakeLogoLoader()).draw_basemap(ax, VIEW)
            assert basemap.attribution in [text.get_text() for text in ax.texts]
        finally:
            plt.close(fig)

    def test_a_provider_with_no_terms_credits_nothing(self):
        fig, ax = plt.subplots()
        try:
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader()).draw_basemap(ax, VIEW)
            assert len(ax.texts) == 0
        finally:
            plt.close(fig)

    def test_the_credit_line_reaches_the_pixels(self, track, tmp_path):
        """OSM's terms require the credit to be visible, not merely carried."""
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=40)
        plain = (
            MatplotlibRenderer(FakeBasemap(), FakeLogoLoader())
            .render(config, track, tmp_path / "a")
            .frame_paths[0]
        )
        credited = (
            MatplotlibRenderer(
                FakeBasemap(attribution="© OpenStreetMap contributors"),
                FakeLogoLoader(),
            )
            .render(config, track, tmp_path / "b")
            .frame_paths[0]
        )
        assert not np.array_equal(plt.imread(plain), plt.imread(credited))


class TestLogoPlacement:
    """Logos are anchored to points on the map, not to canvas corners."""

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
        with_logo = dataclasses.replace(plain, logo_start=str(logo_png))
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

        The fake's default image is opaque, which is what makes the test above
        meaningful.
        """
        plain = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=30)
        invisible = dataclasses.replace(plain, logo_start="car")
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

    def test_a_transparent_logo_keeps_the_view(self, track, tmp_path):
        """imshow resizes the view to whatever it drew, so the limits have to
        be put back; with them restored, a logo never zooms the map."""
        plain = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=30)
        with_logo = dataclasses.replace(plain, logo_start="car")
        renderer = MatplotlibRenderer(
            FakeBasemap(), FakeLogoLoader(np.zeros((4, 4, 4)))
        )
        first = renderer.render(plain, track, tmp_path / "a").frame_paths[0]
        second = renderer.render(with_logo, track, tmp_path / "b").frame_paths[0]
        assert np.array_equal(plt.imread(first), plt.imread(second))
        assert renderer.figure_size(plain) == renderer.figure_size(with_logo)

    def test_each_flag_resolves_its_own_source(self, track, tmp_path):
        config = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=5,
            dpi=20,
            logo_start="a",
            logo_end="b",
            logo_marker="c",
        )
        logos = FakeLogoLoader()
        MatplotlibRenderer(FakeBasemap(), logos).render(config, track, tmp_path)
        assert sorted(logos.calls) == ["a", "b", "c"]

    @pytest.mark.parametrize("field", ["start", "end", "marker"])
    def test_a_single_placement_resolves_only_it(self, track, tmp_path, field):
        config = _single_logo_config(field, "car")
        logos = FakeLogoLoader()
        MatplotlibRenderer(FakeBasemap(), logos).render(config, track, tmp_path)
        assert logos.calls == ["car"]


def _single_logo_config(field: str, source: str) -> RenderConfig:
    """A config with exactly one logo placement, written explicitly so ty can
    see which field is being set — a `**{f"logo_{field}": ...}` spread makes it
    check every field against every value."""
    if field == "start":
        return RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, logo_start=source)
    if field == "end":
        return RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, logo_end=source)
    return RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, logo_marker=source)


@pytest.mark.parametrize("anchor", sorted(LOGO_ANCHORS))
class TestAnchors:
    """Every domain anchor is accepted by the renderer."""

    def test_every_anchor_renders(self, track, tmp_path, anchor):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, dpi=20, logo_start="car")
        result = MatplotlibRenderer(
            FakeBasemap(), FakeLogoLoader(anchor=anchor)
        ).render(config, track, tmp_path)
        assert result.frame_count == 1


class TestLogoGeometry:
    """The geometry helpers, checked directly rather than through a figure."""

    def test_centre_straddles_the_point(self):
        box = _logo_box(_square_logo("center", 20), 100.0, 200.0, (2.0, 3.0))
        assert box == (100.0 - 20.0, 100.0 + 20.0, 200.0 - 30.0, 200.0 + 30.0)

    def test_bottom_sits_the_logo_above_the_point(self):
        box = _logo_box(_square_logo("bottom", 20), 100.0, 200.0, (2.0, 3.0))
        assert box[0:2] == (100.0 - 20.0, 100.0 + 20.0)
        assert box[2] == 200.0

    def test_top_hangs_the_logo_below_the_point(self):
        box = _logo_box(_square_logo("top", 20), 100.0, 200.0, (2.0, 3.0))
        assert box[3] == 200.0

    def test_left_puts_the_logo_left_of_the_point(self):
        box = _logo_box(_square_logo("left", 20), 100.0, 200.0, (2.0, 3.0))
        assert box[1] == 100.0

    def test_right_puts_the_logo_right_of_the_point(self):
        box = _logo_box(_square_logo("right", 20), 100.0, 200.0, (2.0, 3.0))
        assert box[0] == 100.0

    def test_each_axis_converts_through_its_own_scale(self):
        """A square logo is only square on screen if the two scales are used
        separately. A track with a lot of climbing gives a view far taller
        than it is wide, so one data unit is not worth the same pixels on
        both axes, and the height must come from the y scale."""
        square = _square_logo("center", 10)
        box = _logo_box(square, 0.0, 0.0, (2.0, 5.0))
        assert box[1] - box[0] == pytest.approx(20.0)
        assert box[3] - box[2] == pytest.approx(50.0)

    def test_a_wide_image_keeps_its_aspect(self):
        wide = Logo(
            image=np.zeros((8, 16, 4), dtype=float),
            anchor="center",
            size_px=20,
            source="wide",
        )
        box = _logo_box(wide, 0.0, 0.0, (1.0, 1.0))
        assert box[1] - box[0] == pytest.approx(20.0)
        assert box[3] - box[2] == pytest.approx(10.0)

    def test_side_offsets_centre_on_the_point(self):
        assert _side_offsets("center", "center", 4.0, 6.0) == (-2.0, 2.0, -3.0, 3.0)

    def test_side_offsets_put_the_long_side_towards_its_named_neighbour(self):
        assert _side_offsets("left", "above", 4.0, 6.0) == (-4.0, 0.0, 0.0, 6.0)


def _square_logo(anchor: str, size_px: int) -> Logo:
    """A square logo for the geometry helpers."""
    return Logo(
        image=np.zeros((size_px, size_px, 4), dtype=float),
        anchor=anchor,
        size_px=size_px,
        source="car",
    )


class TestLogoSizing:
    """A logo's on-screen size is its pixel size, whatever the canvas."""

    @pytest.mark.parametrize("size", ["16:9", "1:1", "9:16"])
    def test_the_logo_is_size_px_wide_on_screen(self, track, tmp_path, size):
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, dpi=100, size=size, logo_start="car"
        )
        frame = _render_frame(track, tmp_path, config, size_px=40)
        assert _red_width(frame) == pytest.approx(40, abs=1)

    def test_a_rising_dpi_does_not_enlarge_the_logo(self, track, tmp_path):
        """size_px is in device pixels, so a finer frame is a not a bigger logo."""
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, dpi=100, size="1:1", logo_start="car"
        )
        frame = _render_frame(track, tmp_path, config, size_px=40)
        assert _red_width(frame) == pytest.approx(40, abs=1)

    def test_a_wider_request_draws_a_wider_logo(self, track, tmp_path):
        config = RenderConfig(
            duration=0.2, hold=0.0, fps=5, dpi=100, size="1:1", logo_start="car"
        )
        frame = _render_frame(track, tmp_path, config, size_px=80)
        assert _red_width(frame) == pytest.approx(80, abs=1)


def _render_frame(track, tmp_path, config, *, size_px) -> np.ndarray:
    """Render one frame with a red square logo of a known width."""
    result = MatplotlibRenderer(
        FakeBasemap(), FakeLogoLoader(_red_square(), size_px=size_px)
    ).render(config, track, tmp_path)
    return plt.imread(result.frame_paths[0])


def _red_square() -> np.ndarray:
    """Opaque red, so the logo is distinguishable from the default background."""
    square = np.zeros((8, 8, 4), dtype=float)
    square[..., 0] = 1.0
    square[..., 3] = 1.0
    return square


def _red_width(frame: np.ndarray) -> int:
    """The on-screen width in pixels of the red logo in a frame."""
    mask = (frame[..., 0] > 0.9) & (frame[..., 1] < 0.1) & (frame[..., 2] < 0.1)
    columns = np.nonzero(mask.sum(axis=0) > 0)[0]
    return int(columns.max() - columns.min() + 1)


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
