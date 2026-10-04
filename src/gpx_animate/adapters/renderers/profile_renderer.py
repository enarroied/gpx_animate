"""The standalone elevation chart video (US-11).

A second :class:`~gpx_animate.application.ports.FrameRenderer` that draws the
elevation chart and nothing else — no basemap, no track, no HUD, no logos. It
exists because US-11 asks for the chart as its own deliverable, and a separate
renderer is cheaper than a mode flag on :class:`MatplotlibRenderer`, which would
have meant branching over every stage of that much larger ``render`` method.

It is frame-locked with the map video: both derive progress from
:func:`~gpx_animate.adapters.renderers.elevation_chart.revealed_point_count`
and take their frame count from the same ``RenderConfig``, so the two files can
be shown side by side. That is why it reuses ``size``, ``dpi``, ``fps``,
``duration`` and ``hold`` rather than growing knobs of its own — a chart video
that ran to a different length than the map it belongs to would be worse than
useless.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib


matplotlib.use("Agg")
# E402: pyplot must follow matplotlib.use("Agg") or it picks a GUI backend.
import matplotlib.pyplot as plt  # noqa: E402

from gpx_animate.adapters.renderers.elevation_chart import draw_chart_on
from gpx_animate.adapters.renderers.elevation_chart import new_chart_axes
from gpx_animate.adapters.renderers.elevation_chart import revealed_point_count
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)


class ProfileRenderer:
    """Renders the elevation chart on its own, one frame per animation frame."""

    def render(self, config: RenderConfig, track: Track, out_dir: Path) -> RenderResult:
        """Render the chart animation into ``out_dir``.

        Args:
            config: Supplies the frame arithmetic, figure size and colours.
            track: The track whose profile is charted.
            out_dir: Directory to write frames into. Created if missing.

        Returns:
            The frames that were written.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        dists = track.cumulative_distance_km()
        elevations = track.elevations
        n_draw_frames = config.n_draw_frames
        n_frames = config.n_frames
        n_total = len(dists)
        style = config.appearance

        width, height = config.size_inches
        fig, ax = new_chart_axes(style, width, height, config.dpi)
        chart = draw_chart_on(ax, dists, elevations, style)

        logger.info(
            "Rendering %d elevation chart frames (%.1f km, %d m of climbing)",
            n_frames,
            dists[-1] if n_total else 0.0,
            track.elevation_gain_m(),
        )

        frame_paths: list[Path] = []
        for index in range(n_frames):
            n_points = revealed_point_count(index, n_draw_frames, n_total)
            chart.set_progress(dists[n_points - 1] if n_total else 0.0)

            frame_path = out_dir / f"frame_{index:05d}.png"
            # Never transparent: the chart carries its own background, and an
            # alpha channel here would only survive into an MP4 as black.
            fig.savefig(frame_path, dpi=config.dpi, facecolor=fig.get_facecolor())
            frame_paths.append(frame_path)

        plt.close(fig)
        logger.debug("Wrote %d chart frames to %s", n_frames, out_dir)
        return RenderResult(
            frame_dir=out_dir,
            frame_paths=tuple(frame_paths),
            frame_count=n_frames,
        )
