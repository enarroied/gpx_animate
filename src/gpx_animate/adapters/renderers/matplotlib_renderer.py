"""The matplotlib frame renderer.

Draws the same figure the monolith did, frame by frame, with the growing trace
as a ``LineCollection`` whose segments are swapped out per frame. The
basemap and the logo arrive as ports, so this module is the only place that
knows both matplotlib and how a frame is put together.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
import numpy as np
import pyproj


matplotlib.use("Agg")
# E402: pyplot must follow matplotlib.use("Agg") or it picks a GUI backend.
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

from gpx_animate.application.ports import BasemapProvider
from gpx_animate.application.ports import LogoLoader
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)

WEB_MERCATOR = "EPSG:3857"

# Corner anchor for each logo position: (x, y, horizontal align, vertical align).
LOGO_ANCHORS: dict[str, tuple[float, float, str, str]] = {
    "bottom-right": (0.98, 0.05, "right", "bottom"),
    "bottom-left": (0.02, 0.05, "left", "bottom"),
    "top-right": (0.98, 0.95, "right", "top"),
    "top-left": (0.02, 0.95, "left", "top"),
}


class MatplotlibRenderer:
    """Renders animation frames with matplotlib.

    Attributes:
        basemap: Port implementation that draws the map underneath.
        logos: Port implementation that reads logo images. Only used when the
            config asks for a logo.
    """

    def __init__(self, basemap: BasemapProvider, logos: LogoLoader) -> None:
        """Bind the ports the renderer draws through.

        Args:
            basemap: Draws the basemap.
            logos: Reads logo images.
        """
        self.basemap = basemap
        self.logos = logos

    def render(self, config: RenderConfig, track: Track, out_dir: Path) -> RenderResult:
        """Render every frame of the animation into ``out_dir``.

        Args:
            config: Validated render settings.
            track: The track to draw.
            out_dir: Directory for the frames, created if missing.

        Returns:
            The frames, named ``frame_00000.png`` upwards.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        appearance = config.appearance
        dists = track.cumulative_distance_km()
        total_km = dists[-1] if dists else 0.0
        total_gain = track.elevation_gain_m()
        ele = track.elevations

        n_draw_frames = config.n_draw_frames
        n_frames = config.n_frames

        transformer = pyproj.Transformer.from_crs(
            "EPSG:4326", WEB_MERCATOR, always_xy=True
        )
        X, Y = transformer.transform(track.longitudes, track.latitudes)

        width, height = config.size_inches
        fig, ax = plt.subplots(figsize=(width, height), dpi=config.dpi)
        fig.patch.set_facecolor(appearance.bg_color)
        ax.set_facecolor(appearance.bg_color)

        # Bounds with padding. A degenerate track (a single point, or a straight
        # east-west line) has zero extent on one axis, hence the `or 1.0`.
        pad_x = (X.max() - X.min()) * config.margin or 1.0
        pad_y = (Y.max() - Y.min()) * config.margin or 1.0
        ax.set_xlim(X.min() - pad_x, X.max() + pad_x)
        ax.set_ylim(Y.min() - pad_y, Y.max() + pad_y)

        self.basemap.add_basemap(ax, crs=WEB_MERCATOR)

        ax.plot(
            X,
            Y,
            color=appearance.track_faint,
            lw=3,
            alpha=0.7,
            solid_capstyle="round",
            zorder=3,
        )

        # The growing line. One segment per pair of consecutive points; each
        # frame reveals a prefix of them.
        segments = np.stack(
            [
                np.column_stack([X[:-1], Y[:-1]]),
                np.column_stack([X[1:], Y[1:]]),
            ],
            axis=1,
        )
        line = LineCollection(
            [],
            colors=appearance.track_bright,
            linewidths=4,
            capstyle="round",
            joinstyle="round",
            zorder=4,
        )
        ax.add_collection(line)

        (marker,) = ax.plot(
            [],
            [],
            "o",
            color=appearance.marker_color,
            markersize=10,
            markeredgecolor="white",
            markeredgewidth=1.5,
            zorder=5,
        )

        hud = ax.text(
            0.02,
            0.98,
            "",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=12,
            color=appearance.hud_color,
            family=appearance.font,
            zorder=10,
            bbox={
                "boxstyle": "round,pad=0.5",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.75,
            },
        )

        ax.text(
            0.02,
            0.06,
            track.name,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=18,
            weight="bold",
            color=appearance.title_color,
            family=appearance.font,
            zorder=10,
        )

        if config.logo:
            anchor_x, anchor_y, h_align, _ = LOGO_ANCHORS[config.logo_position]
            right_edge = anchor_x - 0.12
            ax.imshow(
                self.logos.load(str(config.logo)),
                transform=ax.transAxes,
                zorder=10,
                extent=(
                    (right_edge, anchor_x, anchor_y, anchor_y + 0.12)
                    if h_align == "right"
                    else (anchor_x, anchor_x + 0.12, anchor_y, anchor_y + 0.12)
                ),
                aspect="auto",
            )

        ax.set_axis_off()
        fig.tight_layout(pad=0)

        frame_paths: list[Path] = []
        for index in range(n_frames):
            # Hold frames reuse the final state.
            progress = (
                index / max(1, n_draw_frames - 1) if index < n_draw_frames else 1.0
            )
            n_points = max(2, int(round(progress * (len(X) - 1))) + 1)
            n_points = min(n_points, len(X))

            # matplotlib's stub types set_segments too narrowly for an ndarray.
            revealed = segments[: n_points - 1]
            line.set_segments(revealed)  # ty: ignore[invalid-argument-type]
            marker.set_data([X[n_points - 1]], [Y[n_points - 1]])

            done_km = dists[n_points - 1]
            done_ele = ele[n_points - 1]
            hud.set_text(
                f"Distance   {done_km:5.1f} / {total_km:.1f} km\n"
                f"Elevation  {done_ele:5.0f} m  (+{total_gain:.0f} m total)"
            )

            frame_path = out_dir / f"frame_{index:05d}.png"
            fig.savefig(frame_path, dpi=config.dpi, facecolor=fig.get_facecolor())
            frame_paths.append(frame_path)

        plt.close(fig)
        logger.debug("Wrote %d frames to %s", n_frames, out_dir)
        return RenderResult(
            frame_dir=out_dir,
            frame_paths=tuple(frame_paths),
            frame_count=n_frames,
        )

    def figure_size(self, config: RenderConfig) -> tuple[int, int]:
        """Pixel size of a rendered frame.

        Args:
            config: Supplies the size preset and the dpi.

        Returns:
            ``(width, height)`` in pixels.
        """
        width, height = config.size_inches
        return round(width * config.dpi), round(height * config.dpi)
