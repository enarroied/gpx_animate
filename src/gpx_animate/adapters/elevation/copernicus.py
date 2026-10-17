"""The ``--dem auto`` elevation source: Copernicus GLO-30 tiles.

Copernicus DEM is published as 1-degree tiles on public S3, so no account and
no key are needed. A tile is roughly 40 MB, which is too much to re-fetch on
every render, so tiles are downloaded once into the user's cache directory and
reused. That is also why the naming maths is pure and unit-tested: getting a
tile name wrong shows up as a 404, not as a wrong place on the map.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import rasterio
import requests
from rasterio.merge import merge as rio_merge
from rasterio.transform import array_bounds
from rasterio.warp import transform_bounds

from gpx_animate.adapters.elevation.reproject import warp_covering
from gpx_animate.adapters.paths import cache_dir
from gpx_animate.application.errors import DemDownloadError
from gpx_animate.application.errors import DemNotReadableError
from gpx_animate.application.ports import ElevationRaster
from gpx_animate.domain.bbox import Bbox


logger = logging.getLogger(__name__)

BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
"""Public S3 bucket hosting the Copernicus GLO-30 tiles."""

USER_AGENT = "gpx-animate (https://github.com/enarroied/gpx_animate)"
"""Identifies the client, as tile hosts' terms require."""

DEM_SUBDIR = Path("dem")
"""Sub-directory under the cache root where tiles are stored."""


def tile_name_for(lat: float, lon: float) -> str:
    """The Copernicus tile containing a point, from its WGS84 position.

    Args:
        lat: Latitude in degrees.
        lon: Longitude in degrees.

    Returns:
        The tile folder name, e.g. ``Copernicus_DSM_COG_10_N42_00_E001_00_DEM``.
    """
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (
        f"Copernicus_DSM_COG_10_{ns}{abs(int(lat // 1)):02d}_00_"
        f"{ew}{abs(int(lon // 1)):03d}_00_DEM"
    )


def tiles_for_bbox(bbox: Bbox) -> set[str]:
    """All Copernicus tiles a lon/lat box touches.

    A box larger than one degree spans several tiles, and a track that wanders
    across a degree line is normal, so the set is returned rather than a single
    tile. The box is assumed to be in degrees (WGS84), which is the only CRS a
    1-degree tile grid makes sense in.

    Args:
        bbox: The area to cover, in degrees.

    Returns:
        The tile names covering the box.
    """
    names = set()
    lat = float(math.floor(bbox.min_y))
    while lat <= math.floor(bbox.max_y):
        lon = float(math.floor(bbox.min_x))
        while lon <= math.floor(bbox.max_x):
            names.add(tile_name_for(lat, lon))
            lon += 1.0
        lat += 1.0
    return names


def _tile_path(cache_root: Path, name: str) -> Path:
    """Where a tile is cached on disk."""
    return cache_root / DEM_SUBDIR / name / f"{name}.tif"


def _download(url: str, destination: Path) -> None:
    """Fetch a URL to ``destination``.

    Args:
        url: The tile's URL.
        destination: Where to write the downloaded bytes.

    Raises:
        DemDownloadError: If the download fails.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(
            url, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}
        ) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise DemDownloadError(f"could not download {url}: {exc}") from exc


class CopernicusDem:
    """Elevations from the public Copernicus GLO-30 tiles, cached on disk.

    Args:
        cache_root: Where tiles are stored. Defaults to the user's cache
            directory; tests pass a temporary one.
    """

    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = Path(cache_root) if cache_root else cache_dir()

    def get_raster(self, bbox: Bbox, crs: str) -> ElevationRaster:
        """Download any needed tiles and return elevations covering ``bbox``.

        Args:
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection.

        Returns:
            The elevation grid in ``crs``.

        Raises:
            DemDownloadError: If a tile cannot be fetched.
            DemNotReadableError: If a tile cannot be opened as a raster.
        """
        deg_bbox = _to_degrees(bbox, crs)
        names = sorted(tiles_for_bbox(deg_bbox))
        logger.info("Copernicus DEM tiles for %s: %s", bbox, ", ".join(names))
        paths = [self._ensure_tile(name) for name in names]
        return self._read(paths, bbox, crs)

    def _ensure_tile(self, name: str) -> Path:
        """Return the cached path for a tile, downloading it if needed.

        Args:
            name: The tile folder name.

        Returns:
            The path to the tile file.

        Raises:
            DemDownloadError: If the tile cannot be downloaded.
        """
        path = _tile_path(self.cache_root, name)
        if path.is_file() and path.stat().st_size > 0:
            return path
        url = f"{BASE_URL}/{name}/{name}.tif"
        logger.info("Downloading Copernicus DEM tile %s", name)
        _download(url, path)
        return path

    def _read(self, paths: list[Path], bbox: Bbox, crs: str) -> ElevationRaster:
        """Read, mosaic if needed, and warp the tiles to cover ``bbox``.

        Args:
            paths: The tile files to read.
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection.

        Returns:
            The elevation grid in ``crs``.

        Raises:
            DemNotReadableError: If a tile cannot be opened as a raster.
        """
        if len(paths) == 1:
            try:
                with rasterio.open(paths[0]) as source:
                    return warp_covering(
                        source.read(1),
                        source.transform,
                        source.crs,
                        bbox,
                        crs,
                        label=str(paths[0]),
                        source_bounds=(
                            source.bounds.left,
                            source.bounds.bottom,
                            source.bounds.right,
                            source.bounds.top,
                        ),
                        src_nodata=source.nodata,
                    )
            except rasterio.errors.RasterioIOError as exc:
                raise DemNotReadableError(
                    f"cannot read DEM tile {paths[0]}: {exc}"
                ) from exc
        return self._mosaic(paths, bbox, crs)

    def _mosaic(self, paths: list[Path], bbox: Bbox, crs: str) -> ElevationRaster:
        """Mosaic several tiles and warp the result to cover ``bbox``.

        Args:
            paths: The tile files to mosaic.
            bbox: The area to cover, in ``crs`` units.
            crs: Target projection.

        Returns:
            The elevation grid in ``crs``.
        """
        sources = [rasterio.open(path) for path in paths]
        try:
            bounds_4326 = transform_bounds(
                crs, "EPSG:4326", bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y
            )
            merged, out_transform = rio_merge(sources, bounds=bounds_4326)
            band = merged[0]
            west, south, east, north = array_bounds(
                band.shape[0], band.shape[1], out_transform
            )
            return warp_covering(
                band,
                out_transform,
                sources[0].crs,
                bbox,
                crs,
                label=str(paths[0]),
                source_bounds=(west, south, east, north),
            )
        finally:
            for source in sources:
                source.close()


def _to_degrees(bbox: Bbox, crs: str) -> Bbox:
    """Reproject a metric bbox to WGS84 degrees for tile lookup.

    Args:
        bbox: The area to cover, in ``crs`` units.
        crs: The projection ``bbox`` is in.

    Returns:
        The same area in degrees.
    """
    if crs == "EPSG:4326":
        return bbox
    left, bottom, right, top = transform_bounds(
        crs, "EPSG:4326", bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y
    )
    return Bbox(left, bottom, right, top)
