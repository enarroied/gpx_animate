"""Shading a basemap with relief from an elevation model.

This is the M9 composition: an underlay (tile style, ``--style none``) carries
the colour, a DEM carries the shape, and the shade is multiplied over the
colour. The result is one :class:`~gpx_animate.application.ports.BasemapImage`
with the underlay's attribution intact -- the OSM credit has to survive, or the
overlay quietly drops the one thing the tile terms require.

The maths is the pure :func:`~gpx_animate.domain.hillshade.shade` and
:func:`~gpx_animate.domain.hillshade.blend`, so what lives here is
orchestration: choose the pixel grid, reproject the DEM onto it, and estimate
the cell size in metres so the slopes mean something.
"""

from __future__ import annotations

import logging

import numpy as np
from rasterio.transform import from_bounds
from rasterio.warp import Resampling
from rasterio.warp import reproject

from gpx_animate.application.ports import BasemapImage
from gpx_animate.application.ports import BasemapProvider
from gpx_animate.application.ports import ElevationProvider
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.hillshade import blend
from gpx_animate.domain.hillshade import shade


logger = logging.getLogger(__name__)

MIN_GRID_DIMENSION = 64
"""Below this the underlay is treated as a placeholder rather than a picture.

``--style none`` returns a 2x2 block, which has no shape to speak of. When the
underlay is that small the grid is taken from the view instead, so a grey
hillshade still comes out at a usable resolution.
"""

STANDALONE_LONG_SIDE = 1024
"""Grid size for a hillshade with no picture under it, on its long side."""


def _grid_for(bbox: Bbox) -> tuple[tuple[int, int], tuple[float, float, float, float]]:
    """A raster grid over ``bbox``, ``STANDALONE_LONG_SIDE`` on its long side.

    Args:
        bbox: The area to cover, in the caller's units.

    Returns:
        The ``(rows, cols)`` and matplotlib ``extent`` of the grid.
    """
    width_m = max(bbox.width, 1.0)
    height_m = max(bbox.height, 1.0)
    if width_m >= height_m:
        cols = STANDALONE_LONG_SIDE
        rows = max(1, int(round(STANDALONE_LONG_SIDE * height_m / width_m)))
    else:
        rows = STANDALONE_LONG_SIDE
        cols = max(1, int(round(STANDALONE_LONG_SIDE * width_m / height_m)))
    return (rows, cols), bbox.extent


def _shade_onto(
    dem: np.ndarray,
    dem_extent: tuple[float, float, float, float],
    dem_crs: str,
    crs: str,
    grid: tuple[int, int],
    extent: tuple[float, float, float, float],
    *,
    azimuth: float,
    altitude: float,
    z_factor: float,
) -> np.ndarray:
    """Reproject a DEM onto a grid and shade it in metres.

    Args:
        dem: ``(rows, cols)`` elevations.
        dem_extent: The DEM's matplotlib ``extent``.
        dem_crs: The DEM's projection.
        crs: The target projection.
        grid: ``(rows, cols)`` of the destination grid.
        extent: The destination grid's matplotlib ``extent``.
        azimuth: Light direction, degrees clockwise from north.
        altitude: Light elevation above the horizon, in degrees.
        z_factor: Vertical exaggeration, already corrected for the projection.

    Returns:
        A ``(rows, cols)`` ``uint8`` shade.
    """
    rows, cols = grid
    destination = np.full(grid, np.nan, dtype=np.float32)
    # rasterio's from_bounds takes (west, south, east, north), i.e. Bbox's
    # order, not matplotlib's extent; convert before handing it a rectangle.
    dem_west, dem_south = dem_extent[0], dem_extent[2]
    dem_east, dem_north = dem_extent[1], dem_extent[3]
    west, south = extent[0], extent[2]
    east, north = extent[1], extent[3]
    source_transform = from_bounds(
        dem_west,
        dem_south,
        dem_east,
        dem_north,
        width=dem.shape[1],
        height=dem.shape[0],
    )
    dst_transform = from_bounds(west, south, east, north, width=cols, height=rows)
    reproject(
        source=dem,
        destination=destination,
        src_transform=source_transform,
        src_crs=dem_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    # Cell size in the target CRS, which the renderer always passes as a metric
    # one (EPSG:3857 by default), so the gradient is metres per pixel and the
    # slopes are real. Web Mercator is conformal and inflates ground distance by
    # 1/cos(latitude), which flattens the apparent relief a little at mid
    # latitudes; the z_factor control is there to compensate if it matters.
    pixel_size_x = max(abs(extent[1] - extent[0]) / max(cols, 1), 1e-6)
    pixel_size_y = max(abs(extent[3] - extent[2]) / max(rows, 1), 1e-6)
    return shade(
        destination,
        pixel_size_x=pixel_size_x,
        pixel_size_y=pixel_size_y,
        azimuth=azimuth,
        altitude=altitude,
        z_factor=z_factor,
    )


class HillshadeBasemap(BasemapProvider):
    """An underlay basemap multiplied by a DEM-derived hillshade.

    Args:
        underlay: The provider that supplies the colour, e.g. tiles.
        elevation: The provider that supplies the DEM.
        azimuth: Light direction, degrees clockwise from north.
        altitude: Light elevation above the horizon, in degrees.
        z_factor: Vertical exaggeration. ``1.0`` is true relief; the cell size
            is computed in metres so this number means something.
        strength: How far toward the full multiply to go, ``0..1``. ``0`` is the
            underlay untouched, so it doubles as a "how much terrain do you
            want" knob.
    """

    def __init__(
        self,
        underlay: BasemapProvider,
        elevation: ElevationProvider,
        *,
        azimuth: float,
        altitude: float,
        z_factor: float,
        strength: float,
    ) -> None:
        self.underlay = underlay
        self.elevation = elevation
        self.azimuth = azimuth
        self.altitude = altitude
        self.z_factor = z_factor
        self.strength = strength

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str = "auto") -> BasemapImage:
        """Fetch the underlay, shade it with the DEM, and return one image.

        Args:
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection.
            zoom: Tile zoom level, or ``"auto"``. Ignored by providers that do
                not use tiles.

        Returns:
            The shaded image over the underlay's extent, carrying the underlay's
            attribution.
        """
        underlay = self.underlay.get_image(bbox, crs, zoom)
        base = np.asarray(underlay.image, dtype=float)
        if base.ndim == 3 and base.shape[2] == 4:
            base = base[..., :3]

        rows, cols = base.shape[:2]
        if rows < MIN_GRID_DIMENSION or cols < MIN_GRID_DIMENSION:
            # A placeholder underlay, so the grid comes from the view instead.
            grid, extent = _grid_for(bbox)
            base = np.full((*grid, 3), 255.0)
        else:
            grid = (rows, cols)
            extent = underlay.extent

        raster = self.elevation.get_raster(bbox, crs)
        shade_grid = _shade_onto(
            np.asarray(raster.image, dtype=np.float32),
            raster.extent,
            raster.crs,
            crs,
            grid,
            extent,
            azimuth=self.azimuth,
            altitude=self.altitude,
            z_factor=self.z_factor,
        )
        blended = blend(base, shade_grid, strength=self.strength)
        logger.debug("Shaded %dx%d hillshade over %s", grid[0], grid[1], underlay.crs)
        return BasemapImage(
            image=blended,
            extent=extent,
            crs=crs,
            attribution=underlay.attribution,
        )
