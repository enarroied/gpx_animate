"""A basemap read from a local GeoTIFF.

This is the ``--tiff`` mode: you bring your own imagery, and nothing is
downloaded. rasterio is a direct dependency rather than an optional extra
because contextily already requires it, so an extra here would buy nothing;
depending on it directly is what keeps a future contextily release from
quietly breaking this module.

The whole file is read, not a window of it, and the result covers the area the
file covers. A GeoTIFF of a few megapixels is fine; a 50 GB elevation model is
not, and the failure to expect there is the machine running out of memory.
Cropping the file down first is the way around it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import array_bounds
from rasterio.warp import Resampling
from rasterio.warp import calculate_default_transform
from rasterio.warp import reproject
from rasterio.warp import transform_bounds

from gpx_animate.application.errors import TiffNotReadableError
from gpx_animate.application.errors import TiffOutsideViewError
from gpx_animate.application.ports import BasemapImage
from gpx_animate.domain.bbox import Bbox


logger = logging.getLogger(__name__)


class TiffBasemap:
    """A basemap read from a local GeoTIFF.

    Attributes:
        path: The file to read.
    """

    def __init__(self, path: Path) -> None:
        """Check the file is there and openable.

        The check happens here rather than at draw time so a typo in a
        ``--tiff`` path fails before any frames are rendered, not 150 frames
        later.

        Args:
            path: The GeoTIFF to read.

        Raises:
            TiffNotReadableError: If the file is missing, unreadable, or not a
                raster rasterio can open.
        """
        self.path = Path(path)
        if not self.path.is_file():
            raise TiffNotReadableError(f"no such GeoTIFF: {self.path}")
        try:
            # Opening is the real test: GDAL rejects a band-less or zero-sized
            # raster itself, so there is nothing to check for before this.
            with rasterio.open(self.path):
                pass
        except rasterio.errors.RasterioIOError as exc:
            raise TiffNotReadableError(
                f"cannot read GeoTIFF {self.path}: {exc}"
            ) from exc

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str = "auto") -> BasemapImage:
        """Read the raster, reprojecting it into ``crs`` if needed.

        Args:
            bbox: The area being rendered. Used to check the file is in the
                right place; the returned image covers the file, not the box.
            crs: Target projection. A raster in another projection is warped.
            zoom: Ignored; there are no tiles to choose a level for.

        Returns:
            The raster as ``(rows, cols, bands)``, uint8.

        Raises:
            TiffNotReadableError: If the file cannot be read, or carries no CRS.
            TiffOutsideViewError: If the file does not overlap ``bbox``.
        """
        with rasterio.open(self.path) as src:
            if src.crs is None:
                raise TiffNotReadableError(
                    f"{self.path} declares no CRS, so there is no way to place "
                    f"it; give it one with `gdal_edit -a_srs {crs} {self.path}`"
                )
            bands = src.read()
            source_crs = src.crs
            transform = src.transform
            covered = Bbox(*src.bounds)

            if source_crs != crs:
                # Warping the whole file, not a window of it: the destination
                # grid has to cover the source area in the new projection, and
                # anything outside that area comes back as zeros.
                transform, width, height = calculate_default_transform(
                    source_crs, crs, src.width, src.height, *src.bounds
                )
                warped = np.zeros((bands.shape[0], height, width), dtype=bands.dtype)
                reproject(
                    source=bands,
                    destination=warped,
                    src_transform=src.transform,
                    src_crs=source_crs,
                    dst_transform=transform,
                    dst_crs=crs,
                    resampling=Resampling.bilinear,
                )
                bands = warped
                # transform_bounds wants (west, south, east, north), which is
                # Bbox's own order; covered.extent is matplotlib's and is
                # transposed, so pass the fields rather than the tuple.
                left, bottom, right, top = transform_bounds(
                    source_crs,
                    crs,
                    covered.min_x,
                    covered.min_y,
                    covered.max_x,
                    covered.max_y,
                )
                covered = Bbox(left, bottom, right, top)

        height, width = bands.shape[1:]
        # array_bounds is (west, south, east, north); the port's extent is
        # matplotlib's (left, right, bottom, top). Identical for a square
        # raster, transposed for anything else.
        west, south, east, north = array_bounds(height, width, transform)
        extent = (west, east, south, north)
        if not covered.overlaps(bbox):
            raise TiffOutsideViewError(
                f"{self.path} covers {covered}, which does not overlap the "
                f"rendered area {bbox}; the GeoTIFF is for somewhere else, or "
                f"its CRS ({source_crs}) is not the one the track is in"
            )
        logger.debug(
            "Read %s: %d bands, %dx%d, extent %s",
            self.path,
            bands.shape[0],
            width,
            height,
            extent,
        )
        return BasemapImage(image=bands.transpose(1, 2, 0), extent=extent, crs=crs)
