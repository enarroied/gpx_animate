"""Colours and fonts. A style is pure data; it never draws anything."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    """The visual treatment drawn on top of the basemap.

    The values here are the ones the monolith shipped as ``CONFIG`` keys. Note
    that they are independent of the basemap style: a dark satellite basemap
    would want different values, which is future work.
    """

    bg_color: str = "#f5f5f2"
    track_faint: str = "#b8b8b8"
    track_bright: str = "#e63946"
    marker_color: str = "#1d3557"
    hud_color: str = "#1d3557"
    title_color: str = "#1d3557"
    font: str = "DejaVu Sans"


DEFAULT_STYLE = Style()
"""The style used when nothing else is requested."""
