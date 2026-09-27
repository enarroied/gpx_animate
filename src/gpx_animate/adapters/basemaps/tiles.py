"""contextily-backed basemap providers.

This is the only module that talks to tile servers, so it is also where the
identifying User-Agent lives: OSM's usage policy requires one, and tile
requests without it get blocked.
"""

from __future__ import annotations

import os
from typing import Any

import contextily as cx


USER_AGENT = (
    "GPX-Animate/1.0 (+https://github.com/enarroied/mess_box/tree/master/gpx_stuff; "
    "eric.narro.ied@gmail.com)"
)
"""Identifies the app to the tile servers, as OSM's usage policy requires.

This is passed explicitly to ``contextily.add_basemap`` below. It is *not* set
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
            KeyError: If the style is unknown. The CLI validates against
                :func:`available_styles` first, so this only fires for a
                programmatic caller.
        """
        self.style = style

    @property
    def provider(self) -> Any:
        """The underlying contextily provider."""
        return TILE_PROVIDERS[self.style]

    def add_basemap(self, axes: Any, **options: Any) -> None:
        """Fetch tiles and draw them onto ``axes``.

        Args:
            axes: The matplotlib axes to draw on.
            **options: Passed through to ``contextily.add_basemap``. These win
                over the defaults below, so a caller can override the zoom
                level without this method knowing about it.

        Raises:
            KeyError: If the style is unknown.
        """
        defaults: dict[str, Any] = {
            "source": self.provider,
            "attribution_size": 6,
            "zoom": "auto",
            "headers": {"User-Agent": USER_AGENT},
        }
        cx.add_basemap(axes, **{**defaults, **options})
