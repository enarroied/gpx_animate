"""A DEM read from a local GeoTIFF, for ``--dem /path/to/file.tif``.

You bring the elevation model and nothing is downloaded. As with ``--tiff``,
rasterio is a direct dependency, the file is validated when the adapter is
built, and only the window covering the view is read.
"""

from __future__ import annotations

import logging
from pathlib import Path

import rasterio

from gpx_animate.adapters.elevation.reproject import read_covering
from gpx_animate.application.errors import DemNotReadableError
from gpx_animate.application.ports import ElevationRaster
from gpx_animate.domain.bbox import Bbox


logger = logging.getLogger(__name__)


class LocalDem:
    """Elevations read from a GeoTIFF on disk.

    Args:
        path: The DEM file to read.
    """

    def __init__(self, path: Path) -> None:
        """Open the file once to fail fast on a missing or unreadable DEM.

        Args:
            path: The DEM file to read.

        Raises:
            DemNotReadableError: If the file does not exist, or cannot be opened
                as a raster.
        """
        self.path = Path(path)
        if not self.path.is_file():
            raise DemNotReadableError(f"DEM file does not exist: {self.path}")
        try:
            with rasterio.open(self.path) as source:
                if source.crs is None:
                    raise DemNotReadableError(f"{self.path} declares no CRS")
        except rasterio.errors.RasterioIOError as exc:
            raise DemNotReadableError(f"cannot read DEM {self.path}: {exc}") from exc

    def get_raster(self, bbox: Bbox, crs: str) -> ElevationRaster:
        """Read the part of the DEM that covers ``bbox``, warped to ``crs``.

        Args:
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection.

        Returns:
            Elevations in metres, ``uint`` free, over the covered extent.
        """
        logger.debug("Reading DEM %s for %s", self.path, bbox)
        with rasterio.open(self.path) as source:
            return read_covering(source, bbox, crs, label=str(self.path))
