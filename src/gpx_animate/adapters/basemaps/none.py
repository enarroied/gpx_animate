"""A basemap that draws nothing at all.

Useful in three places: ``--style none`` for a render with no map, fast offline
test renders, and as the example of how small a
:class:`~gpx_animate.application.ports.BasemapProvider` implementation can be.

The image is fully transparent rather than a block of the background colour,
because the renderer already paints ``appearance.bg_color`` onto the figure and
axes patches. Painting it a second time as an image would be redundant, and
worse than redundant: an opaque block is resampled by matplotlib on its way to
the screen, which moves roughly a third of the background pixels by one 8-bit
level. A transparent block is invisible and leaves the output identical to a
render with no basemap drawn, which is what ``none`` is supposed to mean.

It is a 2x2 block rather than a 1x1 pixel because matplotlib's bilinear
interpolation degenerates on a single pixel.
"""

from __future__ import annotations

import numpy as np

from gpx_animate.application.ports import BasemapImage
from gpx_animate.domain.bbox import Bbox


#: Edge length of the square block returned as the "image". Two, because a
#: 1x1 array upsamples badly under bilinear interpolation.
BLOCK_SIZE = 2


class BlankBasemap:
    """Returns a fully transparent block, ignoring the requested area.

    Attributes:
        color: Accepted for symmetry with the other providers and ignored. The
            background colour is the renderer's business, applied to the axes
            patch, so that ``--style none`` still honours ``appearance.bg_color``.
    """

    def __init__(self, color: str = "white") -> None:
        """Record the colour argument without using it.

        Args:
            color: Unused; kept so callers can pass a background colour
                without special-casing the "no basemap" provider.
        """
        self.color = color

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str = "auto") -> BasemapImage:
        """Build a transparent block covering ``bbox``.

        Args:
            bbox: The area to cover. Recorded in the extent, but the block is
                see-through, so the size of the block does not matter.
            crs: Reported back on the result, so the renderer can tell the
                caller what the extent is expressed in.
            zoom: Ignored; there are no tiles to choose a level for.

        Returns:
            A ``(BLOCK_SIZE, BLOCK_SIZE, 4)`` float image in ``0..1``, RGBA,
            with every alpha zero.
        """
        block = np.zeros((BLOCK_SIZE, BLOCK_SIZE, 4), dtype=float)
        return BasemapImage(image=block, extent=bbox.extent, crs=crs)
