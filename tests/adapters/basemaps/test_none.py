"""The do-nothing basemap, which is what makes offline renders possible."""

import matplotlib
import numpy as np


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from gpx_animate.adapters.basemaps.none import BLOCK_SIZE
from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.domain.bbox import Bbox


VIEW = Bbox(-100.0, -200.0, 100.0, 200.0)


class TestTheImageItReturns:
    def test_is_a_square_block_of_rgba(self):
        image = BlankBasemap("red").get_image(VIEW, "EPSG:3857", "auto")
        assert image.image.shape == (BLOCK_SIZE, BLOCK_SIZE, 4)

    def test_is_fully_transparent(self):
        """Not the background colour -- see-through.

        The renderer paints ``appearance.bg_color`` onto the figure and axes
        patches already, so a solid block would be a second, redundant coat of
        it. Worse, an opaque image is resampled on its way to the screen, which
        shifted about a third of the background pixels by one 8-bit level
        against a render with no basemap at all. Alpha zero keeps the two
        identical, which is what "no basemap" should mean.
        """
        image = BlankBasemap("#123456").get_image(VIEW, "EPSG:3857", "auto")
        assert np.allclose(image.image[..., 3], 0.0)

    def test_draws_nothing_over_the_axes(self):
        """The background still has to be the renderer's colour, unchanged."""
        fig, ax = plt.subplots()
        try:
            ax.set_facecolor("#123456")
            before = ax.patch.get_facecolor()
            image = BlankBasemap().get_image(VIEW, "EPSG:3857", "auto")
            ax.imshow(image.image, extent=image.extent, aspect=ax.get_aspect())
            assert np.allclose(ax.patch.get_facecolor(), before)
        finally:
            plt.close(fig)

    def test_is_flat_across_the_whole_block(self):
        """Every pixel the same, not a ramp that happens to start transparent."""
        image = BlankBasemap("blue").get_image(VIEW, "EPSG:3857", "auto")
        assert len(np.unique(image.image.reshape(-1, 4), axis=0)) == 1

    def test_covers_the_whole_requested_view(self):
        image = BlankBasemap().get_image(VIEW, "EPSG:3857", "auto")
        assert image.extent == VIEW.extent

    def test_reports_the_crs_it_was_asked_for(self):
        image = BlankBasemap().get_image(VIEW, "EPSG:4326", "auto")
        assert image.crs == "EPSG:4326"

    def test_carries_no_attribution(self):
        image = BlankBasemap().get_image(VIEW, "EPSG:3857", "auto")
        assert image.attribution is None

    def test_the_colour_argument_is_ignored(self):
        """It is kept for symmetry, so a nonsense one must not blow up.

        Nothing parses it any more: the colour is the axes patch's job. This
        used to raise ValueError, which is why the argument is still accepted at
        all -- callers pass ``appearance.bg_color`` without special-casing it.
        """
        image = BlankBasemap("not-a-colour").get_image(VIEW, "EPSG:3857", "auto")
        assert np.allclose(image.image[..., 3], 0.0)

    def test_ignores_the_zoom(self):
        """No tiles, so no level to pick; the call must still succeed."""
        assert BlankBasemap().get_image(VIEW, "EPSG:3857", 17).image is not None


class TestDrawnOntoAxes:
    def test_the_image_reaches_the_axes_unchanged(self):
        """The renderer still gets an image, and it is the one handed over."""
        basemap = BlankBasemap()
        image = basemap.get_image(VIEW, "EPSG:3857", "auto")
        fig, ax = plt.subplots()
        try:
            ax.imshow(image.image, extent=image.extent, aspect=ax.get_aspect())
            ax.set_xlim(VIEW.min_x, VIEW.max_x)
            ax.set_ylim(VIEW.min_y, VIEW.max_y)
            drawn = ax.images[0].get_array()
            assert drawn is not None
            assert np.allclose(drawn, image.image.reshape(BLOCK_SIZE, BLOCK_SIZE, 4))
        finally:
            plt.close(fig)
