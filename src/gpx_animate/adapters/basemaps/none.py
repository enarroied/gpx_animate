"""A basemap that draws nothing.

Useful in three places: ``--style none`` for a render with no map at all, fast
offline test renders, and as the example of how small a
:class:`~gpx_animate.application.ports.BasemapProvider` implementation can be.
"""

from __future__ import annotations

from typing import Any


class BlankBasemap:
    """Leaves the axes background showing instead of drawing tiles."""

    def add_basemap(self, axes: Any, **options: Any) -> None:
        """Do nothing.

        Args:
            axes: The matplotlib axes, untouched.
            **options: Ignored; accepted to satisfy the port.
        """
        return
