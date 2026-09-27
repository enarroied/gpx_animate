"""Choosing which basemap provider a config asks for.

The rule is one line of precedence, and putting it in one place is what keeps the
CLI, the config files and the tests from each inventing their own version:
``tiff`` wins over ``style``, and ``style = "none"`` is a real style rather than
a special case in the renderer.
"""

from __future__ import annotations

from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.adapters.basemaps.tiff import TiffBasemap
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.application.ports import BasemapProvider
from gpx_animate.domain.render_config import RenderConfig


NONE_STYLE = "none"
"""The style name that draws the background and no map."""


def style_choices() -> tuple[str, ...]:
    """Every style name ``--style`` accepts on this machine.

    Returns:
        The available tile styles, plus ``none``.
    """
    return (*available_styles(), NONE_STYLE)


def build_basemap(config: RenderConfig) -> BasemapProvider:
    """Build the provider the config asks for.

    Args:
        config: The resolved render config.

    Returns:
        A provider ready to hand to the renderer.

    Raises:
        TiffNotReadableError: If the GeoTIFF cannot be opened.
        TiffOutsideViewError: If it does not overlap the area being drawn.
        BasemapError: If ``style`` names something unavailable.
    """
    if config.tiff is not None:
        return TiffBasemap(config.tiff)
    if config.style == NONE_STYLE:
        # The background colour is passed for symmetry, but BlankBasemap leaves
        # it to the renderer, which paints appearance.bg_color onto the axes.
        return BlankBasemap(color=config.appearance.bg_color)
    return TileBasemap(config.style)
