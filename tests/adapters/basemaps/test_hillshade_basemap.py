"""The hillshade basemap: shading an underlay with a DEM."""

import numpy as np
import pytest
from fakes import FakeBasemap
from fakes import FakeElevation

from gpx_animate.adapters.basemaps.hillshade import HillshadeBasemap
from gpx_animate.domain.bbox import Bbox


VIEW = Bbox(0.0, 0.0, 1000.0, 500.0)
CRS = "EPSG:3857"

SHADE_PARAMS = {"azimuth": 315.0, "altitude": 45.0, "z_factor": 1.0, "strength": 1.0}


def make_underlay(width=128, height=64):
    """A fake basemap that is big enough to be treated as a picture."""
    image = np.full((height, width, 3), 200, dtype=np.uint8)
    return FakeBasemap(image=image)


def make_elevation():
    """A DEM that ramps up to the east so the relief is not flat."""
    return FakeElevation(image=np.tile(np.arange(64, dtype=float), (64, 1)))


class TestShading:
    def test_it_returns_an_image_of_the_underlay_size(self):
        basemap = HillshadeBasemap(make_underlay(), make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert image.image.shape == (64, 128, 3)

    def test_it_shades_the_underlay_pixels(self):
        """The result must differ from the unshaded underlay."""
        basemap = HillshadeBasemap(make_underlay(), make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert not np.all(image.image == 200)

    def test_it_carries_the_underlay_attribution(self):
        underlay = FakeBasemap(attribution="© OpenStreetMap")
        basemap = HillshadeBasemap(underlay, make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert image.attribution == "© OpenStreetMap"

    def test_it_keeps_the_underlay_extent(self):
        underlay = FakeBasemap(image=np.full((64, 64, 3), 200, dtype=np.uint8))
        basemap = HillshadeBasemap(underlay, make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert image.extent == pytest.approx(VIEW.extent)

    def test_zero_strength_leaves_the_underlay_untouched(self):
        params = {**SHADE_PARAMS, "strength": 0.0}
        underlay = make_underlay()
        basemap = HillshadeBasemap(underlay, make_elevation(), **params)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert np.all(image.image == 200)


class TestWithNoPictureUnderlay:
    def test_a_small_placeholder_still_produces_a_usable_grid(self):
        """--style none returns a 2x2 block; the grid must come from the view."""
        underlay = FakeBasemap(image=np.full((2, 2, 3), 255, dtype=np.uint8))
        basemap = HillshadeBasemap(underlay, make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        assert image.image.shape[0] >= 64
        assert image.image.shape[1] >= 64

    def test_the_placeholder_is_grey_relief(self):
        """A white underlay times a shade gives a grey result."""
        underlay = FakeBasemap(image=np.full((2, 2, 3), 255, dtype=np.uint8))
        basemap = HillshadeBasemap(underlay, make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        channels = image.image
        assert np.all(channels[..., 0] == channels[..., 1])
        assert np.all(channels[..., 1] == channels[..., 2])

    def test_the_placeholder_grid_follows_the_aspect(self):
        underlay = FakeBasemap(image=np.full((2, 2, 3), 255, dtype=np.uint8))
        basemap = HillshadeBasemap(underlay, make_elevation(), **SHADE_PARAMS)
        image = basemap.get_image(VIEW, CRS, "auto")
        height, width = image.image.shape[:2]
        assert width > height
