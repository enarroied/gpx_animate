"""Reading a DEM window and warping it into the view's projection.

Both elevation adapters end up here: one has a local file, the other has
downloaded tiles, but the job after opening is the same — take the part of the
raster that covers the view and express it in the view's CRS. Keeping it in one
place means the windowing, the nodata value and the extent order are decided
once rather than twice.
"""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.transform import array_bounds
from rasterio.warp import Resampling
from rasterio.warp import calculate_default_transform
from rasterio.warp import reproject
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from gpx_animate.application.errors import DemNotReadableError
from gpx_animate.application.errors import DemOutsideViewError
from gpx_animate.application.ports import ElevationRaster
from gpx_animate.domain.bbox import Bbox


def _clip_to_bounds(
    requested: tuple[float, float, float, float],
    raster: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Clip a (left, bottom, right, top) box to another, same-order box."""
    req_left, req_bottom, req_right, req_top = requested
    raster_left, raster_bottom, raster_right, raster_top = raster
    return (
        max(req_left, raster_left),
        max(req_bottom, raster_bottom),
        min(req_right, raster_right),
        min(req_top, raster_top),
    )


def warp_covering(
    band: np.ndarray,
    source_transform: Affine,
    source_crs: rasterio.crs.CRS,
    bbox: Bbox,
    dst_crs: str,
    *,
    label: str,
    source_bounds: tuple[float, float, float, float],
    src_nodata: float | None = None,
) -> ElevationRaster:
    """Clip a DEM array to ``bbox`` and warp it to ``dst_crs``.

    Args:
        band: Elevations, ``(rows, cols)``.
        source_transform: Affine of ``band``.
        source_crs: Projection of ``band``.
        bbox: The area to cover, in ``dst_crs`` units.
        dst_crs: Target projection.
        label: The source name used in error messages.
        source_bounds: ``(left, bottom, right, top)`` the array covers, which
            may be larger than the array's own transform if it is a merge.
        src_nodata: No-data value in ``band``, if any.

    Returns:
        The elevation grid in ``dst_crs``.

    Raises:
        DemOutsideViewError: If the source does not intersect ``bbox``.
    """
    requested = transform_bounds(
        dst_crs, source_crs, bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y
    )
    left, bottom, right, top = _clip_to_bounds(requested, source_bounds)
    if left >= right or bottom >= top:
        raise DemOutsideViewError(
            f"{label} is for {Bbox(*source_bounds)}, which does not overlap the "
            f"area being rendered ({bbox})"
        )

    window = from_bounds(left, bottom, right, top, transform=source_transform)
    window = window.round_offsets().round_lengths()
    width = int(window.width)
    height = int(window.height)
    if width < 1 or height < 1:
        raise DemOutsideViewError(
            f"{label} has no elevation pixels inside the area being rendered"
        )

    clipped = band[
        int(window.row_off) : int(window.row_off) + height,
        int(window.col_off) : int(window.col_off) + width,
    ].astype(np.float32)
    window_transform = source_transform * Affine.translation(
        window.col_off, window.row_off
    )

    dest_transform, dest_width, dest_height = calculate_default_transform(
        source_crs, dst_crs, width, height, left, bottom, right, top
    )
    destination = np.full((dest_height, dest_width), np.nan, dtype=np.float32)
    reproject(
        source=clipped,
        destination=destination,
        src_transform=window_transform,
        src_crs=source_crs,
        src_nodata=src_nodata,
        dst_transform=dest_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )

    west, south, east, north = array_bounds(dest_height, dest_width, dest_transform)
    return ElevationRaster(
        image=destination,
        extent=(west, east, south, north),
        crs=dst_crs,
        nodata=float("nan"),
    )


def read_covering(
    source: rasterio.io.DatasetReader,
    bbox: Bbox,
    crs: str,
    *,
    label: str,
) -> ElevationRaster:
    """Read the part of an open DEM covering ``bbox`` and warp it to ``crs``.

    Args:
        source: An open rasterio dataset. Its first band is taken as elevation.
        bbox: The area to cover, in ``crs`` units.
        crs: Target projection.
        label: The file name used in error messages.

    Returns:
        The elevation grid in ``crs``.

    Raises:
        DemNotReadableError: If the raster declares no CRS.
        DemOutsideViewError: If the raster does not intersect ``bbox``.
    """
    if source.crs is None:
        raise DemNotReadableError(
            f"{label} declares no CRS, so there is no way to place it; give it "
            f"one with `gdal_edit -a_srs {crs} {label}`"
        )
    band = source.read(1)
    return warp_covering(
        band,
        source.transform,
        source.crs,
        bbox,
        crs,
        label=label,
        source_bounds=(
            source.bounds.left,
            source.bounds.bottom,
            source.bounds.right,
            source.bounds.top,
        ),
        src_nodata=source.nodata,
    )
