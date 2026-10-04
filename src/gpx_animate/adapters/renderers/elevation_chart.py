"""The elevation chart, drawn as an inset over a parent axes.

Shared by both halves of US-11: the corner overlay on the map video and the
standalone chart video. Only the geometry differs between them — a corner panel
is a fraction of the map axes, the standalone chart fills its own figure — so the
curve, the axes decoration and the progress cursor live here once.

Two matplotlib details in here are load-bearing, and both fail *silently*
rather than raising, which is why they are spelled out in the code:

``mpl_toolkits.axes_grid1.axes_size.from_any(0.28)`` returns a ``Fixed`` — that
is 0.28 **points** — while ``from_any("28%")`` returns a ``Fraction``. A panel
sized with a bare float comes out point-sized and looks like nothing at all.

``inset_axes`` resolves its child's size as a fraction *of the anchor box*, so
the panel size is carried entirely by ``bbox_to_anchor`` and the child is asked
for ``"100%"`` of it. Passing the size twice — once in the anchor box and once in
``width``/``height`` — squares the fraction and quietly halves the panel.

``inset_axes`` also positions its child at *draw* time, and ``fig.tight_layout()``
refuses to lay out inset axes, warning that the result "might be incorrect".
Creating the inset after ``tight_layout`` has run silences the warning and leaves
the parent geometry unchanged; ``set_in_layout(False)`` does not silence it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import matplotlib
import numpy as np


try:
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes
except Exception:  # noqa: BLE001
    inset_axes = None

matplotlib.use("Agg")
# E402: pyplot must follow matplotlib.use("Agg") or it picks a GUI backend.
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from gpx_animate.domain.render_config import FULL_WIDTH_PROFILE_POSITIONS
from gpx_animate.domain.render_config import PROFILE_EDGE_MARGIN
from gpx_animate.domain.render_config import PROFILE_POSITIONS
from gpx_animate.domain.style import Style


FULL_PANEL = "100%"
"""The child fills its anchor box. See the module docstring on sizing."""

CURSOR_ALPHA = 0.8
"""The progress cursor is a hint, not a data series, so it stays translucent."""

CURSOR_LINEWIDTH = 1.5
"""Thicker than the curve so the cursor stays findable over the grid."""

CURVE_LINEWIDTH = 1.5
"""The elevation curve itself."""

FILL_ALPHA = 0.18
"""The area under the curve, light enough to read the curve through it."""

PANEL_ALPHA = 0.82
"""The panel's backing plate. See :func:`draw_chart_on` for why it exists."""

DEGENERATE_SPAN = 1e-9
"""Stand-in span for an axis whose data is a single value.

matplotlib warns and draws nothing when ``xlim``/``ylim`` are equal, which is
what a one-point track or a perfectly flat elevation profile would otherwise
produce.
"""


def revealed_point_count(index: int, n_draw_frames: int, n_total: int) -> int:
    """How many track points are drawn at frame ``index``.

    The single source of truth for animation progress, shared by the map
    renderer and the standalone chart renderer. US-11 requires the two videos to
    be frame-for-frame alignable, and they cannot be if each derives progress on
    its own, so neither is allowed to inline this arithmetic.

    Hold frames — those at or past ``n_draw_frames`` — reuse the final state. The
    result never falls below two points, so the first frame has a segment to
    draw, and never exceeds ``n_total``.

    Args:
        index: Zero-based frame number.
        n_draw_frames: Frames in the drawing phase, before the hold.
        n_total: Total points on the track.

    Returns:
        A point count in ``[2, n_total]``, or ``n_total`` itself when the track
        has fewer than two points.
    """
    progress = index / max(1, n_draw_frames - 1) if index < n_draw_frames else 1.0
    n_points = max(2, int(round(progress * (n_total - 1))) + 1)
    return min(n_points, n_total)


def anchor_box(
    position: str,
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    """The axes-fraction box a chart of this size occupies at this position.

    Derived from ``PROFILE_POSITIONS`` rather than handed to matplotlib as a
    ``loc`` alone, because a corner panel needs the box itself moved in from the
    frame edge — ``loc`` positions the panel *within* the box and cannot express
    the margin. The two anchors are read independently so a corner needs no
    special-casing.

    ``top`` and ``bottom`` span the full frame width and ignore ``width``, which
    is what makes them strips rather than panels. They keep their margin only on
    the edge they sit against. Corners keep ``PROFILE_EDGE_MARGIN`` clear on both
    edges they touch, so a panel never sits flush against the frame.

    Args:
        position: A key of :data:`PROFILE_POSITIONS` other than ``off``.
        width: Panel width as a fraction of the parent axes. Ignored by the
            full-width positions.
        height: Panel height as a fraction of the parent axes.

    Returns:
        ``(x0, y0, width, height)`` in axes fraction.

    Raises:
        ValueError: If ``position`` is ``off`` or unknown.
    """
    if position == "off" or position not in PROFILE_POSITIONS:
        raise ValueError(f"no chart position named {position!r}")
    _, x_anchor, y_anchor = PROFILE_POSITIONS[position]
    full_width = position in FULL_WIDTH_PROFILE_POSITIONS
    if full_width:
        width = 1.0
    margin = 0.0 if full_width else PROFILE_EDGE_MARGIN

    if x_anchor == 0.0:
        x0 = margin
    elif x_anchor == 1.0:
        x0 = 1.0 - width - margin
    else:
        x0 = (1.0 - width) / 2.0

    if y_anchor == 1.0:
        y0 = 1.0 - height
    elif y_anchor == 0.0:
        y0 = margin
    else:
        y0 = (1.0 - height) / 2.0

    return x0, y0, width, height


def _limits(values: np.ndarray) -> tuple[float, float]:
    """A min/max pair that is never equal, for a matplotlib axis limit.

    Args:
        values: The data the axis will show.

    Returns:
        ``(low, high)``, widened by :data:`DEGENERATE_SPAN` when the data does
        not vary, because equal limits draw nothing and warn.
    """
    low = float(values.min())
    high = float(values.max())
    if high - low < DEGENERATE_SPAN:
        return low - DEGENERATE_SPAN, high + DEGENERATE_SPAN
    return low, high


@dataclasses.dataclass
class ChartHandle:
    """The drawn chart, and the one thing about it that changes per frame.

    Attributes:
        axes: The axes the chart was drawn into.
        cursor: The vertical progress line, moved by :meth:`set_progress`.
    """

    axes: Axes
    cursor: Line2D

    def set_progress(self, done_km: float) -> None:
        """Move the cursor to the distance drawn so far.

        The cursor is an ``axvline``, which is a two-point ``Line2D``. Handing
        ``set_xdata`` a *single* value collapses it to zero width and it silently
        draws nothing at all, so the value is repeated to keep both endpoints
        where they belong.

        Args:
            done_km: Cumulative distance drawn, in km.
        """
        self.cursor.set_xdata([done_km, done_km])


def draw_chart_on(
    chart_ax: Axes,
    dists: Sequence[float] | np.ndarray,
    elevations: Sequence[float] | np.ndarray,
    style: Style,
) -> ChartHandle:
    """Draw the curve, the axes decoration and the cursor on a given axes.

    The whole curve is drawn once and indicated by the cursor, not redrawn per
    frame — the chart is a static readout with a moving indicator, so nothing
    needs recomputing per frame except the cursor's position.

    The panel gets a backing plate at :data:`PANEL_ALPHA`. That is not
    decoration: drawn straight over tile texture with no plate, a hairline curve
    is effectively invisible, which is the failure the first attempt at this
    feature shipped.

    Args:
        chart_ax: Axes to draw into. Either an inset or a whole figure's axes.
        dists: Cumulative distance per point, in km.
        elevations: Elevation per point, in m.
        style: Colours for the curve, cursor and text.

    Returns:
        A handle whose :meth:`ChartHandle.set_progress` moves the cursor.
    """
    # Track.cumulative_distance_km hands back a tuple while elevations is an
    # ndarray, so normalise here rather than at each of the two call sites.
    dists = np.asarray(dists)
    elevations = np.asarray(elevations)

    chart_ax.plot(
        dists, elevations, color=style.track_bright, linewidth=CURVE_LINEWIDTH
    )
    chart_ax.fill_between(
        dists, elevations, elevations.min(), color=style.track_bright, alpha=FILL_ALPHA
    )
    chart_ax.set_facecolor(style.bg_color)
    chart_ax.patch.set_alpha(PANEL_ALPHA)
    for spine in chart_ax.spines.values():
        spine.set_color(style.hud_color)
        spine.set_alpha(0.5)
    chart_ax.tick_params(
        colors=style.hud_color, labelcolor=style.hud_color, labelsize=7
    )
    chart_ax.grid(True, alpha=0.2, color=style.hud_color)
    chart_ax.set_xlabel("km", color=style.hud_color, fontsize=7)
    chart_ax.set_ylabel("m", color=style.hud_color, fontsize=7)
    chart_ax.set_xlim(*_limits(dists))
    chart_ax.set_ylim(*_limits(elevations))

    cursor = chart_ax.axvline(
        dists[0],
        color=style.marker_color,
        linewidth=CURSOR_LINEWIDTH,
        alpha=CURSOR_ALPHA,
    )
    return ChartHandle(axes=chart_ax, cursor=cursor)


def add_elevation_chart(
    parent: Axes,
    dists: Sequence[float] | np.ndarray,
    elevations: Sequence[float] | np.ndarray,
    position: str,
    width: float,
    height: float,
    style: Style,
) -> ChartHandle:
    """Draw the elevation chart as an inset over ``parent``.

    Args:
        parent: Axes to place the inset in.
        dists: Cumulative distance per point, in km.
        elevations: Elevation per point, in m.
        position: A key of :data:`PROFILE_POSITIONS` other than ``off``.
        width: Panel width as a fraction of ``parent``.
        height: Panel height as a fraction of ``parent``.
        style: Colours for the curve, cursor and text.

    Returns:
        A handle whose :meth:`ChartHandle.set_progress` moves the cursor.

    Raises:
        RuntimeError: If ``inset_axes`` could not be imported at module load.
        ValueError: If ``position`` is ``off`` or unknown.
    """
    if inset_axes is None:
        raise RuntimeError(
            "matplotlib's axes_grid1 is required for the elevation chart"
        )

    loc, _, _ = PROFILE_POSITIONS[position]
    x0, y0, w, h = anchor_box(position, width, height)
    chart_ax = inset_axes(
        parent,
        width=FULL_PANEL,
        height=FULL_PANEL,
        loc=loc,
        bbox_to_anchor=(x0, y0, w, h),
        bbox_transform=parent.transAxes,
        borderpad=0,
    )
    return draw_chart_on(chart_ax, dists, elevations, style)


def new_chart_axes(
    style: Style,
    width_inches: float,
    height_inches: float,
    dpi: int,
) -> tuple[plt.Figure, Axes]:
    """Create the figure and axes a standalone chart is drawn into.

    Split out from the renderer so the standalone video shares the drawing code
    with the overlay while differing in everything around it. The axes fills the
    frame and keeps its spines and ticks, which the overlay's inset also needs.

    Args:
        style: Supplies the background colour.
        width_inches: Figure width.
        height_inches: Figure height.
        dpi: Figure resolution.

    Returns:
        The ``(figure, axes)`` pair.
    """
    fig = plt.figure(figsize=(width_inches, height_inches), dpi=dpi)
    fig.patch.set_facecolor(style.bg_color)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_facecolor(style.bg_color)
    return fig, ax
