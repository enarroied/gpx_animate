"""Choosing which basemap provider a config asks for.

The rule is one line of precedence, and putting it in one place is what keeps the
CLI, the config files and the tests from each inventing their own version:
``tiff`` wins over ``style``, and ``style = "none"`` is a real style rather than
a special case in the renderer.

``dem`` composes on top of that: whatever the rules above pick as the colour
underlay is wrapped in a :class:`~gpx_animate.adapters.basemaps.hillshade.HillshadeBasemap`
when the config asked for relief. Giving both ``--tiff`` and ``--dem`` is
rejected by the config itself, so there is nothing to decide here about which
one the DEM shades.
"""

from __future__ import annotations

from pathlib import Path

from gpx_animate.adapters.basemaps.hillshade import HillshadeBasemap
from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.adapters.basemaps.tiff import TiffBasemap
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.elevation.copernicus import CopernicusDem
from gpx_animate.adapters.elevation.local import LocalDem
from gpx_animate.application.ports import BasemapProvider
from gpx_animate.application.ports import ElevationProvider
from gpx_animate.domain.render_config import DEM_AUTO
from gpx_animate.domain.render_config import RenderConfig


NONE_STYLE = "none"
"""The style name that draws the background and no map."""


def style_choices() -> tuple[str, ...]:
    """Every style name ``--style`` accepts on this machine.

    Returns:
        The available tile styles, plus ``none``.
    """
    return (*available_styles(), NONE_STYLE)


def build_elevation(dem: str, *, cache_root: Path | None = None) -> ElevationProvider:
    """Build the elevation provider a ``--dem`` value asks for.

    Args:
        dem: ``"auto"`` for Copernicus tiles, otherwise a path to a GeoTIFF.
        cache_root: Where Copernicus tiles are cached, for tests.

    Returns:
        A provider ready to hand to :class:`HillshadeBasemap`.

    Raises:
        DemNotReadableError: If a local path is missing or unreadable.
        DemDownloadError: If a Copernicus tile cannot be fetched.
    """
    if dem == DEM_AUTO:
        return CopernicusDem(cache_root=cache_root)
    return LocalDem(Path(dem))


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
        DemNotReadableError: If the DEM cannot be opened.
        DemDownloadError: If a Copernicus tile cannot be fetched.
    """
    if config.tiff is not None:
        underlay = TiffBasemap(config.tiff)
    elif config.style == NONE_STYLE:
        # The background colour is passed for symmetry, but BlankBasemap leaves
        # it to the renderer, which paints appearance.bg_color onto the axes.
        underlay = BlankBasemap(color=config.appearance.bg_color)
    else:
        underlay = TileBasemap(config.style)

    if config.dem is None:
        return underlay

    return HillshadeBasemap(
        underlay,
        build_elevation(config.dem),
        azimuth=config.hillshade_azimuth,
        altitude=config.hillshade_altitude,
        z_factor=config.hillshade_z,
        strength=config.hillshade_strength,
    )
