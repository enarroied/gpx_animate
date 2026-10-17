"""The local DEM adapter: reading elevations from a GeoTIFF you supply."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from gpx_animate.adapters.elevation.local import LocalDem
from gpx_animate.application.errors import DemNotReadableError
from gpx_animate.application.errors import DemOutsideViewError
from gpx_animate.domain.bbox import Bbox


SIZE = 20
WEB_MERCATOR = "EPSG:3857"
WGS84_BOUNDS = (7.0, 45.0, 7.1, 45.1)
"""left, bottom, right, top of the fixture, an Alpine patch in degrees."""


def write_dem_file(
    path: Path,
    *,
    crs: str | None = "EPSG:4326",
    bounds: tuple[float, float, float, float] = WGS84_BOUNDS,
    values: np.ndarray | None = None,
    size: int = SIZE,
) -> Path:
    """Write a single-band float DEM and return its path.

    Args:
        path: Where to write.
        crs: Projection to declare, or ``None`` for none.
        bounds: ``(left, bottom, right, top)`` in ``crs``.
        values: ``(size, size)`` pixel values, or a ramp.
        size: Pixels per side.

    Returns:
        The path written.
    """
    if values is None:
        values = np.linspace(500.0, 1500.0, size * size, dtype="float32").reshape(
            size, size
        )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_bounds(*bounds, width=size, height=size),
    ) as dst:
        dst.write(values, 1)
    return path


def mercator_view(
    bounds: tuple[float, float, float, float] = WGS84_BOUNDS,
) -> Bbox:
    """The 3857 box the given degrees cover, as a :class:`Bbox`."""
    return Bbox(*transform_bounds("EPSG:4326", WEB_MERCATOR, *bounds))


@pytest.fixture
def dem_path(tmp_path):
    """A valid 20x20 float GeoTIFF in WGS84 over the Alps."""
    return write_dem_file(tmp_path / "dem.tif")


class TestOpening:
    def test_a_valid_file_is_accepted(self, dem_path):
        assert LocalDem(dem_path).path == dem_path

    def test_a_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(DemNotReadableError, match="does not exist"):
            LocalDem(tmp_path / "nope.tif")

    def test_a_directory_is_rejected(self, tmp_path):
        with pytest.raises(DemNotReadableError):
            LocalDem(tmp_path)

    def test_something_that_is_not_a_raster_is_rejected(self, tmp_path):
        junk = tmp_path / "junk.tif"
        junk.write_text("not a tiff at all")
        with pytest.raises(DemNotReadableError, match="cannot read DEM"):
            LocalDem(junk)

    def test_a_file_with_no_crs_is_rejected(self, tmp_path):
        path = write_dem_file(tmp_path / "nocrs.tif", crs=None)
        with pytest.raises(DemNotReadableError, match="no CRS"):
            LocalDem(path)


class TestTheRasterItReturns:
    def test_it_returns_two_dimensional_elevations(self, dem_path):
        raster = LocalDem(dem_path).get_raster(mercator_view(), WEB_MERCATOR)
        assert raster.image.ndim == 2
        assert raster.crs == WEB_MERCATOR

    def test_it_reports_the_requested_crs(self, dem_path):
        raster = LocalDem(dem_path).get_raster(mercator_view(), WEB_MERCATOR)
        assert raster.crs == WEB_MERCATOR

    def test_the_extent_lands_in_the_requested_projection(self, dem_path):
        raster = LocalDem(dem_path).get_raster(mercator_view(), WEB_MERCATOR)
        west, south, east, north = transform_bounds(
            "EPSG:4326", WEB_MERCATOR, *WGS84_BOUNDS
        )
        for got, want in zip(raster.extent, (west, east, south, north), strict=True):
            assert got == pytest.approx(want, abs=1_000)

    def test_it_keeps_the_elevation_values(self, dem_path):
        raster = LocalDem(dem_path).get_raster(mercator_view(), WEB_MERCATOR)
        assert 400.0 < np.nanmean(raster.image) < 1600.0

    def test_row_zero_is_the_northern_edge(self, dem_path):
        """The port's convention: the renderer draws with origin="upper"."""
        values = np.zeros((SIZE, SIZE), dtype="float32")
        values[: SIZE // 2, :] = 100.0
        values[SIZE // 2 :, :] = 900.0
        path = write_dem_file(dem_path.parent / "north.tif", values=values)
        raster = LocalDem(path).get_raster(mercator_view(), WEB_MERCATOR)
        assert np.nanmean(raster.image[0]) < np.nanmean(raster.image[-1])


class TestWindowing:
    def test_it_reads_only_the_part_covering_the_view(self, tmp_path):
        """A DEM larger than the view must not dictate the returned extent."""
        wide = write_dem_file(
            tmp_path / "wide.tif", bounds=(7.0, 45.0, 8.0, 46.0), size=200
        )
        view = mercator_view((7.4, 45.4, 7.5, 45.5))
        raster = LocalDem(wide).get_raster(view, WEB_MERCATOR)
        for got, want in zip(raster.extent, view.extent, strict=True):
            assert got == pytest.approx(want, abs=5_000)

    def test_a_dem_that_does_not_overlap_is_rejected(self, tmp_path):
        ander = write_dem_file(tmp_path / "ander.tif", bounds=(20.0, 10.0, 20.1, 10.1))
        with pytest.raises(DemOutsideViewError, match="does not overlap"):
            LocalDem(ander).get_raster(mercator_view(), WEB_MERCATOR)
