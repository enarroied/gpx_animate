"""Shipped defaults: the bottom layer of the config stack.

SPECS section 5 asks for defaults in one file, never mutated, overridable by
config files and the environment. The defaults themselves live on the domain
types, because that is what makes them validated; this module is the single
place that composes them.

The layers above it are in the same package: :mod:`gpx_animate.config.layers`
reads one source, and :mod:`gpx_animate.config.loader` stacks them. They start
from :func:`default_config` and never mutate it.
"""

from __future__ import annotations

from gpx_animate.domain.render_config import SIZE_PRESETS
from gpx_animate.domain.render_config import GifConfig
from gpx_animate.domain.render_config import RenderConfig


SIZES = SIZE_PRESETS
"""Output aspect presets, keyed by CLI name."""

DEFAULT_BASEMAP_STYLE = "topo"
"""Basemap used when ``--style`` is not given."""


def default_config() -> RenderConfig:
    """Return the shipped defaults.

    Returns:
        A fresh frozen config. Being frozen, it cannot be mutated by accident;
        overrides are made with ``dataclasses.replace``.
    """
    return RenderConfig(style=DEFAULT_BASEMAP_STYLE, gif=GifConfig())
