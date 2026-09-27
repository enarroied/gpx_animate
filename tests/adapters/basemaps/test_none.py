"""The blank basemap, which is what makes offline renders possible."""

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gpx_animate.adapters.basemaps.none import BlankBasemap


def test_leaves_the_axes_untouched():
    fig, ax = plt.subplots()
    try:
        before = ax.images
        BlankBasemap().add_basemap(ax, crs="EPSG:3857")
        assert len(ax.images) == len(before) == 0
    finally:
        plt.close(fig)


def test_accepts_any_options():
    """The port passes renderer hints; ignoring them is the whole point."""
    assert BlankBasemap().add_basemap(object(), crs="EPSG:3857", zoom="auto") is None


def test_the_axes_background_survives():
    """What a --style none render shows: the configured background colour."""
    fig, ax = plt.subplots()
    try:
        ax.set_facecolor("#123456")
        BlankBasemap().add_basemap(ax)
        assert np.allclose(ax.get_facecolor(), (0.07, 0.20, 0.34, 1.0), atol=0.01)
    finally:
        plt.close(fig)
