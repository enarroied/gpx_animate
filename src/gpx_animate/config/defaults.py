"""Shipped defaults, and the place the override layers will be stacked.

SPECS section 5 asks for defaults in one file, never mutated, overridable by
config files and the environment. The defaults themselves live on the domain
types, because that is what makes them validated; this module is the single
place that composes them and the seam the later layers attach to.

Not implemented yet, and therefore not here: the user and project TOML files
and the ``GPX_ANIMATE_*`` environment variables from layers 2 to 4. They land
in M3 alongside the timestamped output directory, which needs the same
resolution logic.
"""

from __future__ import annotations

from gpx_animate.domain.render_config import SIZE_PRESETS
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
    return RenderConfig(style=DEFAULT_BASEMAP_STYLE)
