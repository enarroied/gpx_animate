"""The --tiff basemap: reading a local GeoTIFF instead of downloading tiles.

The fixture writes a 10x10 RGB raster rather than committing a binary, so the
test says what it contains: 100 pixels in EPSG:3857 over a known extent.
"""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from gpx_animate.adapters.basemaps.tiff import TiffBasemap
from gpx_animate.application.errors import TiffNotReadableError
from gpx_animate.application.errors import TiffOutsideViewError
from gpx_animate.domain.bbox import Bbox


SIZE = 10
"""The fixture is 10x10 pixels, per SPECS."""

WEB_MERCATOR = "EPSG:3857"

BOUNDS = (-500000.0, -400000.0, 500000.0, 400000.0)
"""left, bottom, right, top of the fixture, the order rasterio's from_bounds takes:
a chunk of the Alps in Web Mercator."""

VIEW = Bbox(-500000.0, -400000.0, 500000.0, 400000.0)
"""A view that covers the fixture exactly."""

ALPINE_VIEW = Bbox(700000.0, 4900000.0, 900000.0, 5700000.0)
"""Where the 4326 fixture below lands once projected, in Web Mercator."""


def write_geotiff(
    path: Path,
    *,
    crs: str | None = WEB_MERCATOR,
    extent: tuple[float, float, float, float] = BOUNDS,
    bands: int = 3,
    values: np.ndarray | None = None,
) -> Path:
    """Write a small RGB GeoTIFF and return its path.

    Args:
        path: Where to write.
        crs: Projection to declare, or ``None`` to declare none at all.
        extent: ``(left, bottom, right, top)`` of the raster.
        bands: How many bands to write.
        values: Pixel values, broadcast to ``(bands, SIZE, SIZE)``.

    Returns:
        The path written, for convenience.
    """
    pixels = (
        np.arange(bands * SIZE * SIZE, dtype="uint8").reshape(bands, SIZE, SIZE)
        if values is None
        else values
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=bands,
        dtype="uint8",
        crs=crs,
        transform=from_bounds(*extent, width=SIZE, height=SIZE),
    ) as dst:
        dst.write(pixels)
    return path


@pytest.fixture
def tiff_path(tmp_path):
    """A valid 10x10 GeoTIFF in Web Mercator."""
    return write_geotiff(tmp_path / "basemap.tif")


class TestOpening:
    def test_a_valid_file_is_accepted(self, tiff_path):
        assert TiffBasemap(tiff_path).path == tiff_path

    def test_a_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(TiffNotReadableError, match="no such GeoTIFF"):
            TiffBasemap(tmp_path / "nope.tif")

    def test_a_directory_is_rejected(self, tmp_path):
        with pytest.raises(TiffNotReadableError):
            TiffBasemap(tmp_path)

    def test_something_that_is_not_a_raster_is_rejected(self, tmp_path):
        junk = tmp_path / "junk.tif"
        junk.write_text("not a tiff at all")
        with pytest.raises(TiffNotReadableError, match="cannot read GeoTIFF"):
            TiffBasemap(junk)

    def test_a_file_with_no_crs_is_rejected_at_draw_time(self, tmp_path):
        """A raster with no projection cannot be placed, so say so plainly."""
        path = write_geotiff(tmp_path / "nocrs.tif", crs=None)
        with pytest.raises(TiffNotReadableError, match="declares no CRS"):
            TiffBasemap(path).get_image(VIEW, WEB_MERCATOR, "auto")


class TestTheImageItReturns:
    def test_has_the_shape_of_the_file(self, tiff_path):
        """Rows, columns and bands, as imshow wants them."""
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.image.shape == (SIZE, SIZE, 3)

    def test_keeps_the_pixels(self, tiff_path):
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        expected = np.arange(3 * SIZE * SIZE, dtype="uint8").reshape(3, SIZE, SIZE)
        assert np.array_equal(image.image, expected.transpose(1, 2, 0))

    def test_reports_the_files_own_extent(self, tiff_path):
        """In the port's (left, right, bottom, top) order, not rasterio's."""
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.extent == pytest.approx(Bbox(*BOUNDS).extent)

    def test_reports_the_crs_asked_for(self, tiff_path):
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.crs == WEB_MERCATOR

    def test_carries_no_attribution(self, tiff_path):
        """A local file has no third-party tile terms attached to it."""
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.attribution is None

    def test_a_single_band_raster_still_works(self, tmp_path):
        path = write_geotiff(tmp_path / "grey.tif", bands=1)
        image = TiffBasemap(path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.image.shape == (SIZE, SIZE, 1)

    def test_ignores_the_zoom(self, tiff_path):
        image = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, 3)
        assert image.image.shape == (SIZE, SIZE, 3)


class TestReprojection:
    def test_warps_a_raster_in_another_projection(self, tmp_path):
        """A 4326 GeoTIFF must come back in 3857, since that is what the track is in."""
        path = write_geotiff(
            tmp_path / "wgs84.tif", crs="EPSG:4326", extent=(7.0, 45.0, 7.1, 45.1)
        )
        image = TiffBasemap(path).get_image(ALPINE_VIEW, WEB_MERCATOR, "auto")
        west, south, east, north = transform_bounds(
            "EPSG:4326", "EPSG:3857", 7.0, 45.0, 7.1, 45.1
        )
        # The warped grid has square pixels snapped to whole numbers of them, so
        # the extent lands within about half a pixel of the ideal one rather than
        # exactly on it. Half a pixel here is ~680 m.
        for got, want in zip(image.extent, (west, east, south, north), strict=True):
            assert got == pytest.approx(want, abs=1_000)

    def test_a_reprojected_raster_that_overlaps_is_accepted(self, tmp_path):
        """A 4326 GeoTIFF under the track must not be turned away."""
        path = write_geotiff(
            tmp_path / "equator.tif", crs="EPSG:4326", extent=(10.0, 10.0, 10.1, 10.1)
        )
        view = Bbox(*transform_bounds("EPSG:4326", "EPSG:3857", 10.0, 10.0, 10.1, 10.1))
        image = TiffBasemap(path).get_image(view, WEB_MERCATOR, "auto")
        assert image.crs == WEB_MERCATOR

    def test_a_reprojection_elsewhere_is_reported_in_the_right_place(self, tmp_path):
        """The refusal message must name where the file really is.

        Regression. The covered area is recomputed with ``transform_bounds``,
        which takes ``(west, south, east, north)`` -- the order ``Bbox`` uses, and
        not matplotlib's ``extent``. Handing it the transposed tuple does not
        fail loudly: lon_min lands in the ``left`` slot and lat_max in ``top``,
        so the x-min and y-max come out right by luck, and the box is merely
        too big. The damage is in the other two edges, min_y and max_x, which
        is exactly what a user reads to work out why their file was rejected --
        so all four edges are pinned here.
        """
        path = write_geotiff(
            tmp_path / "equator.tif", crs="EPSG:4326", extent=(10.0, 10.0, 10.1, 10.1)
        )
        with pytest.raises(TiffOutsideViewError) as caught:
            TiffBasemap(path).get_image(VIEW, WEB_MERCATOR, "auto")
        west, south, east, north = transform_bounds(
            "EPSG:4326", "EPSG:3857", 10.0, 10.0, 10.1, 10.1
        )
        message = str(caught.value)
        for edge, value in (
            ("min_x", west),
            ("min_y", south),
            ("max_x", east),
            ("max_y", north),
        ):
            assert f"{edge}={value!r}" in message

    def test_a_mercator_raster_is_taller_than_it_is_wide(self, tmp_path):
        """The signature of a correct warp: 0.1 degrees square on the ground is
        11.1 km wide but 15.7 km tall in Web Mercator, which stretches
        north-south by 1/cos(latitude). Forgetting that stretch would come out
        the other way round.

        The exact ratio is not asserted: the destination grid uses square pixels
        and a whole number of them, so it lands on 12x8 rather than the ideal
        1.414:1. That quantisation is rasterio's business, not the provider's.
        """
        path = write_geotiff(
            tmp_path / "wgs84.tif", crs="EPSG:4326", extent=(7.0, 45.0, 7.1, 45.1)
        )
        image = TiffBasemap(path).get_image(ALPINE_VIEW, WEB_MERCATOR, "auto")
        assert image.extent[3] - image.extent[2] > image.extent[1] - image.extent[0]

    def test_a_raster_already_in_the_target_projection_is_not_resampled(
        self, tiff_path
    ):
        """Identity must be a pass-through, or every render would soften the map."""
        first = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        second = TiffBasemap(tiff_path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert np.array_equal(first.image, second.image)


class TestPlacement:
    def test_rejects_a_raster_from_another_part_of_the_world(self, tmp_path):
        """A TIFF of Patagonia under an Alpine track: a clear error, not a blank frame."""
        path = write_geotiff(
            tmp_path / "patagonia.tif",
            extent=(-7500000.0, -4000000.0, -7000000.0, -3500000.0),
        )
        with pytest.raises(TiffOutsideViewError, match="does not overlap"):
            TiffBasemap(path).get_image(VIEW, WEB_MERCATOR, "auto")

    def test_accepts_a_raster_that_merely_overlaps(self, tmp_path):
        """A tighter-than-view raster is normal: the track is framed inside it."""
        path = write_geotiff(
            tmp_path / "tight.tif", extent=(-100.0, -100.0, 100.0, 100.0)
        )
        image = TiffBasemap(path).get_image(VIEW, WEB_MERCATOR, "auto")
        assert image.extent == pytest.approx((-100.0, 100.0, -100.0, 100.0))
