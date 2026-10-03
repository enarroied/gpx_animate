"""The matplotlib frame renderer.

Draws the same figure the monolith did, frame by frame, with the growing trace
as a ``LineCollection`` whose segments are swapped out per frame. The
basemap and the logo arrive as ports, so this module is the only place that
knows both matplotlib and how a frame is put together.

The basemap arrives as an image rather than being drawn by its own provider, so
this is also where it is placed: the provider decides *what* the map is, this
decides where it goes and who has to be credited for it.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from pathlib import Path

import matplotlib
import numpy as np
import pyproj
from matplotlib import patheffects
from matplotlib.patches import FancyBboxPatch


matplotlib.use("Agg")
# E402: pyplot must follow matplotlib.use("Agg") or it picks a GUI backend.
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.image import AxesImage  # noqa: E402

from gpx_animate.application.ports import BasemapProvider
from gpx_animate.application.ports import Logo
from gpx_animate.application.ports import LogoLoader
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.logo import LOGO_ANCHORS
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.track import Track


logger = logging.getLogger(__name__)

WEB_MERCATOR = "EPSG:3857"

ATTRIBUTION_SIZE = 6
"""Point size for a tile provider's credit line.

Six is small but legible over a map, and it is what the tiles were drawn at
before the basemap port existed, so the frames do not shift.
"""

LOGO_ZORDER = 10
"""Draw order for logos. Above the track and the head marker, so a logo is never
half-hidden behind the line it is annotating."""

LOGO_BACKPLATE_ZORDER = LOGO_ZORDER - 1
"""Draw order for a logo's white plate. Between the marker at 5 and the logo
itself at 10, so the plate covers the line but never the logo it frames."""

LOGO_BACKPLATE_PAD_FRACTION = 0.1
"""How much white the plate adds around a logo, as a fraction of each side.

The pad has to scale with the logo rather than be a fixed pixel count, or a
192-px badge would carry the same 2-px border as a 24-px one."""


def _has_visible_pixels(image: np.ndarray) -> bool:
    """Whether a logo image has any opaque pixel to draw.

    A fully transparent image would contribute nothing but would, if it were
    given a plate, print a white blob over the map. An RGB image has no alpha
    to be empty, so it is always visible.

    Args:
        image: The RGBA (or RGB) pixel buffer of a resolved logo.

    Returns:
        True if any pixel is opaque, or the image has no alpha channel.
    """
    return image.shape[2] < 4 or bool(np.any(image[..., 3] > 0))


def _plate_bounds(
    box: tuple[float, float, float, float],
    pad_fraction: float,
) -> tuple[float, float, float, float]:
    """Inflate a logo box by the backplate pad, as ``(x, y, width, height)``.

    Args:
        box: The logo's ``(min_x, max_x, min_y, max_y)`` extent.

    Returns:
        The plate's ``(x, y, width, height)``, x/y being the lower-left corner.
    """
    x0, x1, y0, y1 = box
    width = x1 - x0
    height = y1 - y0
    pad_x = pad_fraction * width
    pad_y = pad_fraction * height
    return x0 - pad_x, y0 - pad_y, width + 2 * pad_x, height + 2 * pad_y


def _logo_plate(
    box: tuple[float, float, float, float],
    units_per_px: tuple[float, float],
    dpi: int,
    pad_fraction: float,
) -> FancyBboxPatch:
    """The rounded white plate shown behind a positioned logo.

    The corner radius is a fraction of the smaller side, in points, so the
    plate stays readable however the logo is sized.

    Args:
        box: The logo's ``(min_x, max_x, min_y, max_y)`` extent.
        units_per_px: ``(x, y)`` data units per device pixel.
        dpi: Figure dpi, to turn a pixel radius into points.

    Returns:
        An unstyled white patch ready to be added to the axes.
    """
    x, y, width, height = _plate_bounds(box, pad_fraction)
    radius_pts = (
        pad_fraction
        * min(width / units_per_px[0], height / units_per_px[1])
        * 72.0
        / dpi
    )
    return FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad={radius_pts:.3f}",
        mutation_scale=1,
        facecolor="white",
        edgecolor="none",
        zorder=LOGO_BACKPLATE_ZORDER,
    )


def _projected_bounds(bounds: Bbox, transformer) -> Bbox:
    """Move a ``--bounds`` window from degrees into the render's projection.

    Web Mercator maps degrees monotonicly onto x and y (no dateline-crossing
    wrapping within the validated ``[-180, 180]`` window), so projecting just
    the two corners and reframing with min/max of the results gives the same
    box the track would have if it filled the window.

    Args:
        bounds: The requested view, in WGS84 degrees.
        transformer: pyproj transformer from EPSG:4326 to the projection the
            track is already drawn in.

    Returns:
        The same window, in projected units, unpadded.
    """
    x, y = transformer.transform(
        [bounds.min_x, bounds.max_x], [bounds.min_y, bounds.max_y]
    )
    x, y = np.asarray(x), np.asarray(y)
    return Bbox(x.min(), y.min(), x.max(), y.max())


def _side_offsets(
    side_x: str, side_y: str, width: float, height: float
) -> tuple[float, float, float, float]:
    """Offsets from an anchor point to the image box, as ``(x0, x1, y0, y1)``.

    Args:
        side_x: Which side of the point the image body falls on, horizontally.
        side_y: The same, vertically.
        width: Image width in data units.
        height: Image height in data units.

    Returns:
        The box, in the point's own coordinates rather than absolute ones.
    """
    x0 = {"left": -width, "center": -width / 2, "right": 0.0}[side_x]
    y0 = {"below": -height, "center": -height / 2, "above": 0.0}[side_y]
    return x0, x0 + width, y0, y0 + height


def _logo_box(
    logo: Logo, x: float, y: float, units_per_px: tuple[float, float]
) -> tuple[float, float, float, float]:
    """Place a logo on a point, in the data units of the axes.

    ``size_px`` is a width in device pixels of the finished frame, so it has to
    be converted through the axes' own scale to become data units. The view is
    fixed for the whole render, so one conversion covers every frame, which is
    what lets the marker logo keep a constant on-screen size while it travels.

    Each side is converted through *its own* axis scale, not derived from the
    other. The axes is square in pixels but the padded view is usually not
    square in data units — a track with a lot of climbing in it is tall and
    narrow — so the two axes disagree on how many data units a pixel is. Taking
    the width in x units and reusing it as a height in y units would stretch or
    squash every logo to suit the shape of the track.

    Args:
        logo: The image and its placement.
        x: Anchor point on the x axis, in data units.
        y: Anchor point on the y axis, in data units.
        units_per_px: ``(x, y)`` data units per device pixel.

    Returns:
        An ``imshow`` extent, ``(min_x, max_x, min_y, max_y)``.
    """
    units_x, units_y = units_per_px
    width = logo.size_px * units_x
    height = logo.size_px * logo.aspect * units_y
    side_x, side_y = LOGO_ANCHORS[logo.anchor]
    dx0, dx1, dy0, dy1 = _side_offsets(side_x, side_y, width, height)
    return x + dx0, x + dx1, y + dy0, y + dy1


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

    def render(self, config: RenderConfig, track: Track, out_dir: Path) -> RenderResult:  # noqa: PLR0915
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
        has_logo = any(
            logo is not None
            for logo in (config.logo_start, config.logo_end, config.logo_marker)
        )
        if has_logo:
            fig.patch.set_facecolor("none")
            ax.set_facecolor("none")
        else:
            fig.patch.set_facecolor(appearance.bg_color)
            ax.set_facecolor(appearance.bg_color)

        # Bounds with padding. A degenerate track (a single point, or a straight
        # east-west line) has zero extent on one axis; Bbox.padded falls back to
        # a one-unit pad there so the view is still drawable.
        if config.bounds is not None:
            # The user fixed the view, so the track's own extent and any margin
            # are irrelevant: show exactly the requested window.
            view = _projected_bounds(config.bounds, transformer)
        else:
            view = Bbox(X.min(), Y.min(), X.max(), Y.max()).padded(config.margin)
        ax.set_xlim(view.min_x, view.max_x)
        ax.set_ylim(view.min_y, view.max_y)

        self.draw_basemap(ax, view)

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

        ax.set_axis_off()
        fig.tight_layout(pad=0)

        marker_logo = self._draw_logos(ax, config, X, Y, view, fig)

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
            if marker_logo is not None:
                marker_logo(X[n_points - 1], Y[n_points - 1])

            done_km = dists[n_points - 1]
            done_ele = ele[n_points - 1]
            hud.set_text(
                f"Distance   {done_km:5.1f} / {total_km:.1f} km\n"
                f"Elevation  {done_ele:5.0f} m  (+{total_gain:.0f} m total)"
            )

            frame_path = out_dir / f"frame_{index:05d}.png"
            fig.savefig(
                frame_path,
                dpi=config.dpi,
                facecolor=fig.get_facecolor(),
                transparent=has_logo,
            )
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

    def _draw_logos(
        self,
        axes: Axes,
        config: RenderConfig,
        xs: np.ndarray,
        ys: np.ndarray,
        view: Bbox,
        fig: plt.Figure,
    ) -> Callable[[float, float], None] | None:
        """Draw the start, end and marker logos, if any were asked for.

        The start and end logos are static, so they are drawn once. The marker
        is handed back as a callable that moves it, since it follows the head of
        the growing line.

        The axes' pixel size is only known once the figure has been laid out and
        drawn at least once, which is why this runs after ``tight_layout`` and
        makes the renderer do one throwaway draw. That is the price of a logo
        size expressed in pixels rather than as a fraction of the canvas, which
        is the only version of "size" that means the same thing in a thumbnail
        and in a 4K export.

        Args:
            axes: The axes to draw on.
            config: Says which logos were requested.
            xs: Track longitudes, projected.
            ys: Track latitudes, projected.
            view: The area on screen, for the pixel-to-data conversion.
            fig: The figure, used to realise the axes geometry.

        Returns:
            A callable that moves the marker logo to a point, or ``None`` when
            no marker logo was requested.
        """
        wanted = {
            "start": config.logo_start,
            "end": config.logo_end,
            "marker": config.logo_marker,
        }
        logos = {key: self.logos.resolve(src) for key, src in wanted.items() if src}
        if not logos:
            return None
        if config.logo_size_px is not None:
            # One --logo-size overrides every placement's resolved size.
            logos = {
                key: dataclasses.replace(logo, size_px=config.logo_size_px)
                for key, logo in logos.items()
            }

        fig.canvas.draw()
        box = axes.get_window_extent()
        units_per_px = (
            (view.max_x - view.min_x) / box.width,
            (view.max_y - view.min_y) / box.height,
        )

        for key, x, y in (("start", xs[0], ys[0]), ("end", xs[-1], ys[-1])):
            logo = logos.get(key)
            if logo is None or not _has_visible_pixels(logo.image):
                continue
            logo_box = _logo_box(logo, x, y, units_per_px)
            if config.logo_plate_padding > 0:
                axes.add_patch(
                    _logo_plate(
                        logo_box, units_per_px, config.dpi, config.logo_plate_padding
                    )
                )
            axes.imshow(
                logo.image,
                extent=logo_box,
                aspect="auto",
                origin="upper",
                zorder=LOGO_ZORDER,
            )
            logger.debug("Drew %s logo %r at (%.1f, %.1f)", key, logo.source, x, y)

        move_marker: Callable[[float, float], None] | None = None
        moving = logos.get("marker")
        if moving is not None and _has_visible_pixels(moving.image):
            initial = _logo_box(moving, xs[0], ys[0], units_per_px)
            plate = None
            if config.logo_plate_padding > 0:
                plate = _logo_plate(
                    initial, units_per_px, config.dpi, config.logo_plate_padding
                )
                axes.add_patch(plate)
            image = axes.imshow(
                moving.image,
                extent=initial,
                aspect="auto",
                origin="upper",
                zorder=LOGO_ZORDER,
            )

            def move_marker(
                x: float,
                y: float,
                image: AxesImage = image,
                plate: FancyBboxPatch | None = plate,
            ) -> None:
                logo_box = _logo_box(moving, x, y, units_per_px)
                image.set_extent(logo_box)
                if plate is not None:
                    plate.set_bounds(
                        *_plate_bounds(logo_box, config.logo_plate_padding)
                    )

        # imshow resizes the view to whatever it drew, so put the frame back.
        # A logo on the last point legitimately hangs outside the view and must
        # not be clipped to it, so this is limits only, not a clip box.
        axes.set_xlim(view.min_x, view.max_x)
        axes.set_ylim(view.min_y, view.max_y)
        return move_marker

    def draw_basemap(self, axes: Axes, view: Bbox) -> None:
        """Draw the basemap image over ``view``.

        The provider is asked for the padded view, not the track itself, so the
        map covers the same ground as the axes including the margin. The axes
        limits are set again afterwards because ``imshow`` otherwise resizes the
        view to the image, which for a partial raster would shrink the frame
        onto whatever the map happens to cover.

        Args:
            axes: The matplotlib axes to draw on.
            view: The area to fill, in :data:`WEB_MERCATOR` units.
        """
        basemap = self.basemap.get_image(view, WEB_MERCATOR, "auto")
        axes.imshow(
            basemap.image,
            extent=basemap.extent,
            interpolation="bilinear",
            aspect=axes.get_aspect(),
        )
        axes.set_xlim(view.min_x, view.max_x)
        axes.set_ylim(view.min_y, view.max_y)
        if basemap.attribution:
            self.draw_attribution(axes, basemap.attribution)

    def draw_attribution(self, axes: Axes, text: str) -> None:
        """Credit a tile provider, as its terms of use require.

        Args:
            axes: The axes to write on.
            text: The credit line the provider asked for.
        """
        axes.text(
            0.005,
            0.005,
            text,
            transform=axes.transAxes,
            size=ATTRIBUTION_SIZE,
            path_effects=[patheffects.withStroke(linewidth=2, foreground="w")],
        )
