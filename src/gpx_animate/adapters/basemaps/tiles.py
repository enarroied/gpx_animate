"""contextily-backed basemap providers.

This is the only module that talks to tile servers, so it is also where the
identifying User-Agent lives: OSM's usage policy requires one, and tile
requests without it get blocked.

The provider fetches an image with ``contextily.bounds2img`` and hands it back
rather than drawing it, which is what lets the renderer, and not this module,
decide how the basemap is placed. ``add_basemap`` used to do that drawing; the
two calls it made internally, ``bounds2img`` then ``warp_tiles``, are made here
explicitly so the resulting pixels are unchanged.
"""

from __future__ import annotations

import os
from typing import Any

import contextily as cx

from gpx_animate.application.errors import BasemapError
from gpx_animate.application.ports import BasemapImage
from gpx_animate.domain.bbox import Bbox


USER_AGENT = (
    "GPX-Animate/1.0 (+https://github.com/enarroied/mess_box/tree/master/gpx_stuff; "
    "eric.narro.ied@gmail.com)"
)
"""Identifies the app to the tile servers, as OSM's usage policy requires.

This is passed explicitly to ``contextily.bounds2img`` below. It is *not* set
through ``requests.utils.default_headers()``, which the monolith did: that call
builds a fresh dict on every invocation, so the mutation never took effect.
"""


def _carto(url_template: str, key_env: str = "CARTO_API_KEY") -> dict[str, Any] | None:
    """Build a Carto provider dict, injecting the API key if available.

    Args:
        url_template: URL with a ``{key}`` placeholder.
        key_env: Environment variable holding the key.

    Returns:
        A provider dict, or ``None`` when no key is configured.
    """
    key = os.environ.get(key_env)
    if not key:
        return None  # signal: leave the style out of the catalogue
    return {
        "url": url_template.replace("{key}", key),
        "attribution": "© OpenStreetMap contributors, © CARTO",
        "max_zoom": 20,
    }


def _providers() -> dict[str, Any]:
    """Assemble the tile providers available right now.

    The Carto entries are built at import time, so a style only appears if
    ``CARTO_API_KEY`` was set when the process started. Changing the
    environment later has no effect.
    """
    return {
        # xyzservices.providers is populated at runtime by Bunch, so the type
        # checker cannot see these members.
        "osm": cx.providers.OpenStreetMap.Mapnik,  # ty: ignore[unresolved-attribute]
        "topo": cx.providers.OpenTopoMap,  # ty: ignore[unresolved-attribute]
        "satellite": cx.providers.Esri.WorldImagery,  # ty: ignore[unresolved-attribute]
        "positron": _carto(
            "https://basemaps.cartocdn.com/rastertiles/positron/{z}/{x}/{y}.png?key={key}"
        ),
        "voyager": _carto(
            "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key={key}"
        ),
        "dark": _carto(
            "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key={key}"
        ),
    }


TILE_PROVIDERS: dict[str, Any] = {
    name: provider for name, provider in _providers().items() if provider is not None
}


def available_styles() -> tuple[str, ...]:
    """Names of the basemap styles that can be used right now.

    Returns:
        Style names, which is what the CLI offers as choices.
    """
    return tuple(TILE_PROVIDERS)


class TileBasemap:
    """A basemap drawn from an online tile provider.

    Attributes:
        style: Name of the tile provider to draw.
    """

    def __init__(self, style: str) -> None:
        """Resolve a style name to a provider.

        Args:
            style: One of :func:`available_styles`.

        Raises:
            BasemapError: If the style is unknown. The CLI validates against
                :func:`available_styles` first, so this is mostly for a
                programmatic caller or a config file naming a style that is not
                available on this machine.
        """
        if style not in TILE_PROVIDERS:
            raise BasemapError(
                f"unknown basemap style {style!r}; "
                f"available: {', '.join(available_styles())}"
            )
        self.style = style

    @property
    def provider(self) -> Any:
        """The underlying contextily provider."""
        return TILE_PROVIDERS[self.style]

    @property
    def attribution(self) -> str | None:
        """The copyright line this style's terms require, if it has one."""
        return self.provider.get("attribution")

    def get_image(self, bbox: Bbox, crs: str, zoom: int | str = "auto") -> BasemapImage:
        """Download the tiles covering ``bbox`` and reproject them.

        Args:
            bbox: Area to cover, in ``crs`` units. The coordinates are passed to
                ``bounds2img`` unchanged because web tiles are addressed in
                Spherical Mercator, which is the renderer's ``crs``.
            crs: Target projection for the returned image. Anything rasterio
                understands works, including the identity case.
            zoom: Tile zoom, or ``"auto"`` to pick one from the bbox.

        Returns:
            The merged tiles, reprojected to ``crs``, with the provider's
            attribution line attached.
        """
        image, extent = cx.bounds2img(
            bbox.min_x,
            bbox.min_y,
            bbox.max_x,
            bbox.max_y,
            zoom=zoom,
            source=self.provider,
            headers={"User-Agent": USER_AGENT},
            ll=False,
        )
        # Always warp, even into the projection the tiles are already in:
        # add_basemap did, and the bilinear round trip is visible in the pixels.
        image, extent = cx.warp_tiles(image, extent, t_crs=crs)
        return BasemapImage(
            image=image,
            extent=extent,
            crs=crs,
            attribution=self.attribution,
        )
