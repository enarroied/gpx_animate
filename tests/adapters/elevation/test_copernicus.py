"""The Copernicus DEM adapter: tile naming and caching, offline.

The real download is exercised by the ``integration``-marked test; everything
else here is pure naming maths or a cache hit, so it runs in the offline suite.
"""

from pathlib import Path

import pytest
from rasterio.warp import transform_bounds

from gpx_animate.adapters.elevation.copernicus import CopernicusDem
from gpx_animate.adapters.elevation.copernicus import _to_degrees
from gpx_animate.adapters.elevation.copernicus import tile_name_for
from gpx_animate.adapters.elevation.copernicus import tiles_for_bbox
from gpx_animate.adapters.paths import cache_dir
from gpx_animate.domain.bbox import Bbox


ALPINE = Bbox(7.0, 45.0, 7.1, 45.1)


class TestTileNaming:
    def test_it_names_the_north_east_tile(self):
        assert tile_name_for(42.9, 1.8) == "Copernicus_DSM_COG_10_N42_00_E001_00_DEM"

    def test_it_names_the_south_west_tile(self):
        name = tile_name_for(-42.9, -1.8)
        assert name.startswith("Copernicus_DSM_COG_10_S")
        assert "_E" not in name
        assert "_W" in name

    def test_it_counts_down_from_the_southern_hemisphere(self):
        """-42.9 is inside the tile whose southern edge is -43, not -42."""
        assert tile_name_for(-42.9, 1.0) == "Copernicus_DSM_COG_10_S43_00_E001_00_DEM"

    def test_it_counts_down_from_the_western_hemisphere(self):
        assert tile_name_for(1.0, -1.8) == "Copernicus_DSM_COG_10_N01_00_W002_00_DEM"


class TestTilesForBbox:
    def test_a_small_box_is_one_tile(self):
        assert tiles_for_bbox(ALPINE) == {"Copernicus_DSM_COG_10_N45_00_E007_00_DEM"}

    def test_a_box_spanning_a_degree_line_is_several_tiles(self):
        """0.9..1.1 longitude straddles the tile boundary at 1 degree."""
        box = Bbox(0.9, 44.5, 1.1, 44.6)
        assert len(tiles_for_bbox(box)) == 2


class TestDegreesConversion:
    def test_it_leaves_a_degree_box_alone(self):
        assert _to_degrees(ALPINE, "EPSG:4326") == ALPINE

    def test_it_projects_a_metric_box_back_to_degrees(self):
        metric = Bbox(*transform_bounds("EPSG:4326", "EPSG:3857", *ALPINE))
        degrees = _to_degrees(metric, "EPSG:3857")
        for got, want in zip(degrees, ALPINE, strict=True):
            assert got == pytest.approx(want, abs=1e-4)


class TestCaching:
    def test_a_cached_tile_is_not_downloaded_again(self, tmp_path):
        """A second render must not re-fetch the same 40 MB file."""
        dem = CopernicusDem(cache_root=tmp_path)
        name = "Copernicus_DSM_COG_10_N45_00_E007_00_DEM"
        cached = tmp_path / "dem" / name / f"{name}.tif"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"pretend this is a geotiff")
        assert dem._ensure_tile(name) == cached
        assert cached.read_bytes() == b"pretend this is a geotiff"

    def test_it_uses_a_subdirectory_of_the_cache_root(self, tmp_path):
        dem = CopernicusDem(cache_root=tmp_path)
        name = "Copernicus_DSM_COG_10_N45_00_E007_00_DEM"
        assert dem._ensure_tile(name).parent == tmp_path / "dem" / name

    def test_the_default_cache_root_is_under_the_users_cache(self):
        assert CopernicusDem().cache_root == cache_dir()


@pytest.mark.integration
def test_it_downloads_and_reads_the_alpine_tile():
    """End-to-end: one real tile, cached, then a small window read from it."""
    west, south, east, north = transform_bounds(
        "EPSG:4326", "EPSG:3857", 7.0, 45.0, 7.1, 45.1
    )
    dem = CopernicusDem(cache_root=Path("/tmp/gpx-animate-test-dem"))
    raster = dem.get_raster(Bbox(west, south, east, north), "EPSG:3857")
    assert raster.image.ndim == 2
    assert raster.crs == "EPSG:3857"
    assert 0 < raster.image.shape[0] < 500
    assert 0 < raster.image.shape[1] < 500
