"""The shared elevation chart: geometry, progress and the cursor."""

import warnings

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402

from gpx_animate.adapters.renderers import elevation_chart  # noqa: E402
from gpx_animate.adapters.renderers.elevation_chart import (  # noqa: E402
    add_elevation_chart,
)
from gpx_animate.adapters.renderers.elevation_chart import anchor_box  # noqa: E402
from gpx_animate.adapters.renderers.elevation_chart import draw_chart_on  # noqa: E402
from gpx_animate.adapters.renderers.elevation_chart import new_chart_axes  # noqa: E402
from gpx_animate.adapters.renderers.elevation_chart import (  # noqa: E402
    revealed_point_count,
)
from gpx_animate.domain.render_config import DEFAULT_STYLE  # noqa: E402
from gpx_animate.domain.render_config import PROFILE_EDGE_MARGIN  # noqa: E402
from gpx_animate.domain.render_config import PROFILE_POSITIONS  # noqa: E402


WIDTH = 0.28
HEIGHT = 0.22

DISTS = np.linspace(0.0, 40.0, 200)
ELEVATIONS = 500.0 + 80.0 * np.sin(np.linspace(0.0, 6.0, 200))


@pytest.fixture
def parent():
    """A figure-filling axes, which is what the renderer hands the chart."""
    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=50)
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    yield ax
    plt.close(fig)


class TestRevealedPointCount:
    def test_first_frame_draws_a_minimum_of_two_points(self):
        """Otherwise there is no segment to draw and frame zero is blank."""
        assert revealed_point_count(0, 10, 100) == 2

    def test_last_draw_frame_reveals_everything(self):
        assert revealed_point_count(9, 10, 100) == 100

    def test_hold_frames_reuse_the_final_state(self):
        assert revealed_point_count(10, 10, 100) == 100
        assert revealed_point_count(99, 10, 100) == 100

    def test_progress_is_monotonic(self):
        counts = [revealed_point_count(i, 20, 100) for i in range(20)]
        assert counts == sorted(counts)

    def test_never_exceeds_the_track(self):
        """A short track must not be asked for points it does not have."""
        assert revealed_point_count(9, 10, 5) == 5

    def test_a_one_point_track_yields_that_point(self):
        assert revealed_point_count(0, 1, 1) == 1

    def test_a_single_draw_frame_does_not_divide_by_zero(self):
        """n_draw_frames - 1 is zero here, so the max(1, ...) guard is load-bearing."""
        count = revealed_point_count(0, 1, 50)
        assert 2 <= count <= 50

    def test_round_trips_progress_through_the_track(self):
        """The last draw frame and the first hold frame agree."""
        assert revealed_point_count(4, 5, 100) == revealed_point_count(5, 5, 100)


class TestAnchorBox:
    @pytest.mark.parametrize("position", sorted(set(PROFILE_POSITIONS) - {"off"}))
    def test_every_position_produces_a_box_inside_the_axes(self, position):
        x0, y0, width, height = anchor_box(position, WIDTH, HEIGHT)
        assert 0.0 <= x0 <= 1.0
        assert 0.0 <= y0 <= 1.0
        assert x0 + width <= 1.0
        assert y0 + height <= 1.0

    @pytest.mark.parametrize(
        ("position", "expected"),
        [
            ("bottom-left", (PROFILE_EDGE_MARGIN, PROFILE_EDGE_MARGIN)),
            ("bottom-right", (1.0 - WIDTH - PROFILE_EDGE_MARGIN, PROFILE_EDGE_MARGIN)),
            ("top-left", (PROFILE_EDGE_MARGIN, 1.0 - HEIGHT)),
            ("top-right", (1.0 - WIDTH - PROFILE_EDGE_MARGIN, 1.0 - HEIGHT)),
        ],
    )
    def test_corners_keep_the_edge_margin(self, position, expected):
        x0, y0, _, _ = anchor_box(position, WIDTH, HEIGHT)
        assert (round(x0, 9), round(y0, 9)) == expected

    @pytest.mark.parametrize("position", ["top", "bottom"])
    def test_full_width_positions_ignore_the_requested_width(self, position):
        """top and bottom are strips, so profile_width must not shrink them."""
        _, _, width, _ = anchor_box(position, WIDTH, HEIGHT)
        assert width == 1.0

    @pytest.mark.parametrize("position", ["top", "bottom"])
    def test_full_width_positions_sit_flush_horizontally(self, position):
        x0, _, width, _ = anchor_box(position, WIDTH, HEIGHT)
        assert x0 == 0.0
        assert width == 1.0

    def test_full_width_positions_keep_no_vertical_margin(self):
        """A strip touching the edge is the point of a strip."""
        _, bottom_y, _, _ = anchor_box("bottom", WIDTH, HEIGHT)
        _, top_y, _, top_h = anchor_box("top", WIDTH, HEIGHT)
        assert bottom_y == 0.0
        assert top_y + top_h == 1.0

    def test_top_and_bottom_are_vertically_mirrored(self):
        _, bottom_y, _, bottom_h = anchor_box("bottom", WIDTH, HEIGHT)
        _, top_y, _, top_h = anchor_box("top", WIDTH, HEIGHT)
        assert bottom_h == top_h
        assert round(top_y, 9) == round(1.0 - bottom_y - bottom_h, 9)

    def test_off_has_no_box(self):
        with pytest.raises(ValueError, match="no chart position named 'off'"):
            anchor_box("off", WIDTH, HEIGHT)

    def test_an_unknown_position_is_rejected(self):
        with pytest.raises(ValueError, match="no chart position named 'sideways'"):
            anchor_box("sideways", WIDTH, HEIGHT)

    def test_a_centred_anchor_centres_the_panel(self, monkeypatch):
        """No current position is centred, so the rule is pinned directly.

        The table drives the box, not a hard-coded corner list, so a future
        middle-anchored position has to land centred rather than wherever the
        last branch happened to fall through to.
        """
        monkeypatch.setitem(
            elevation_chart.PROFILE_POSITIONS,
            "middle",
            ("center", 0.5, 0.5),
        )
        _, y0, _, height = anchor_box("middle", WIDTH, HEIGHT)
        assert y0 == pytest.approx((1.0 - height) / 2.0)


class TestPanelPlacement:
    """The measured panel must land where anchor_box said it would.

    inset_axes resolves its position at draw time and takes its size as a
    fraction of the anchor box, so both are easy to get subtly wrong in a way
    that raises nothing. These assert the pixels.
    """

    @pytest.mark.parametrize("position", sorted(set(PROFILE_POSITIONS) - {"off"}))
    def test_panel_lands_in_the_requested_corner(self, parent, position):
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, position, WIDTH, HEIGHT, DEFAULT_STYLE
        )
        parent.figure.canvas.draw()

        frame = parent.get_window_extent()
        panel = handle.axes.get_window_extent()
        expected_x, expected_y, expected_w, expected_h = anchor_box(
            position, WIDTH, HEIGHT
        )

        assert panel.x0 == pytest.approx(frame.x0 + expected_x * frame.width, abs=1.5)
        assert panel.y0 == pytest.approx(frame.y0 + expected_y * frame.height, abs=1.5)
        assert panel.width == pytest.approx(expected_w * frame.width, abs=1.5)
        assert panel.height == pytest.approx(expected_h * frame.height, abs=1.5)

    def test_a_bottom_left_panel_is_smaller_than_the_frame(self, parent):
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "bottom-left", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        parent.figure.canvas.draw()
        frame = parent.get_window_extent()
        panel = handle.axes.get_window_extent()
        assert panel.width < frame.width
        assert panel.height < frame.height

    def test_a_wider_setting_makes_a_wider_panel(self, parent):
        """Guards against the size being ignored, which is the float trap."""
        narrow = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "top-left", 0.20, HEIGHT, DEFAULT_STYLE
        )
        parent.figure.canvas.draw()
        narrow_width = narrow.axes.get_window_extent().width
        narrow.axes.remove()

        wide = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "top-left", 0.45, HEIGHT, DEFAULT_STYLE
        )
        parent.figure.canvas.draw()
        wide_width = wide.axes.get_window_extent().width

        assert wide_width > narrow_width * 2


class TestCursor:
    def test_the_cursor_has_two_points(self, parent):
        """One point collapses an axvline to zero width and it never draws."""
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "bottom-left", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        assert np.asarray(handle.cursor.get_xdata()).size == 2

    def test_the_cursor_starts_at_the_origin_of_the_track(self, parent):
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "bottom-left", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        assert np.asarray(handle.cursor.get_xdata()).tolist() == [DISTS[0], DISTS[0]]

    def test_set_progress_moves_the_cursor(self, parent):
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "bottom-left", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        handle.set_progress(12.5)
        assert np.asarray(handle.cursor.get_xdata()).tolist() == [12.5, 12.5]

    def test_set_progress_keeps_both_points_together(self, parent):
        """Two points at different x would be a diagonal, not a cursor."""
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "top-right", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        handle.set_progress(30.0)
        xs = np.asarray(handle.cursor.get_xdata())
        assert xs.size == 2
        assert xs[0] == xs[1]

    def test_set_progress_actually_moves_the_pixels(self, parent):
        """A line with two identical x values still has to change position."""
        handle = add_elevation_chart(
            parent, DISTS, ELEVATIONS, "top", WIDTH, HEIGHT, DEFAULT_STYLE
        )
        parent.figure.canvas.draw()
        first = handle.cursor.get_window_extent()

        handle.set_progress(DISTS[-1])
        parent.figure.canvas.draw()
        second = handle.cursor.get_window_extent()

        assert first.x0 != second.x0
        assert second.width == pytest.approx(first.width, abs=1.5)


class TestDrawChartOn:
    def test_it_draws_the_whole_curve_up_front(self, parent):
        handle = draw_chart_on(parent, DISTS, ELEVATIONS, DEFAULT_STYLE)
        assert len(handle.axes.lines) >= 2  # the curve and the cursor

    def test_it_accepts_the_distance_tuple_the_domain_returns(self, parent):
        """Track.cumulative_distance_km hands back a tuple, not an ndarray."""
        handle = draw_chart_on(parent, tuple(DISTS), ELEVATIONS, DEFAULT_STYLE)
        assert handle.axes.get_xlim() == pytest.approx((DISTS[0], DISTS[-1]))

    def test_the_axes_span_the_whole_data_range(self, parent):
        # DISTS is monotonic, so [0]/-[1] are the range; the bare ndarray
        # min()/max() overloads resolve differently between Python versions.
        handle = draw_chart_on(parent, DISTS, ELEVATIONS, DEFAULT_STYLE)
        low, high = handle.axes.get_xlim()
        assert low == pytest.approx(DISTS[0])
        assert high == pytest.approx(DISTS[-1])

    def test_the_elevation_axis_spans_the_whole_range(self, parent):
        handle = draw_chart_on(parent, DISTS, ELEVATIONS, DEFAULT_STYLE)
        low, high = handle.axes.get_ylim()
        assert low == pytest.approx(min(ELEVATIONS.tolist()))
        assert high == pytest.approx(max(ELEVATIONS.tolist()))

    def test_the_panel_has_a_backing_plate(self, parent):
        """Without one a hairline curve over tile texture is invisible."""
        draw_chart_on(parent, DISTS, ELEVATIONS, DEFAULT_STYLE)
        assert parent.get_facecolor()[:3] == pytest.approx(
            to_rgba(DEFAULT_STYLE.bg_color)[:3]
        )

    def test_the_plate_is_not_fully_opaque(self, parent):
        """A solid plate would hide the map; it is a hint of a backing."""
        draw_chart_on(parent, DISTS, ELEVATIONS, DEFAULT_STYLE)
        assert 0.0 < parent.patch.get_alpha() < 1.0

    def test_a_flat_profile_does_not_warn(self, parent):
        """Equal axis limits draw nothing, so they are widened instead."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            draw_chart_on(
                parent, np.array([2.0, 2.0]), np.array([7.0, 7.0]), DEFAULT_STYLE
            )

    def test_a_single_point_track_does_not_warn(self, parent):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            draw_chart_on(parent, np.array([1.0]), np.array([7.0]), DEFAULT_STYLE)

    def test_a_tuple_of_length_one_is_handled(self, parent):
        handle = draw_chart_on(parent, (1.0,), (7.0,), DEFAULT_STYLE)
        assert handle.axes.get_xlim()[1] > handle.axes.get_xlim()[0]


class TestNewChartAxes:
    def test_the_axes_fills_the_figure(self):
        fig, ax = new_chart_axes(DEFAULT_STYLE, 8.0, 4.5, 50)
        try:
            assert ax.get_position().bounds == pytest.approx((0.0, 0.0, 1.0, 1.0))
        finally:
            plt.close(fig)

    def test_the_background_is_the_configured_colour(self):
        fig, _ = new_chart_axes(DEFAULT_STYLE, 8.0, 4.5, 50)
        try:
            assert fig.get_facecolor()[:3] == pytest.approx(
                to_rgba(DEFAULT_STYLE.bg_color)[:3]
            )
        finally:
            plt.close(fig)

    def test_the_axes_keeps_its_spines(self):
        """The standalone chart is a real chart, so it keeps its axes on."""
        fig, ax = new_chart_axes(DEFAULT_STYLE, 8.0, 4.5, 50)
        try:
            assert ax.axison
        finally:
            plt.close(fig)


class TestMissingInsetSupport:
    def test_a_missing_inset_axes_is_reported_clearly(self, parent, monkeypatch):
        """A silent no-chart is the failure mode this feature already had once."""
        monkeypatch.setattr(elevation_chart, "inset_axes", None)
        with pytest.raises(RuntimeError, match="axes_grid1 is required"):
            add_elevation_chart(
                parent, DISTS, ELEVATIONS, "bottom-left", WIDTH, HEIGHT, DEFAULT_STYLE
            )
