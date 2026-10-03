"""Logo placement vocabulary.

US-5 anchors a logo to a *point* on the map — the track's start, its end, or
the moving head of the growing line — so an anchor has to say which part of the
image touches that point. That is a different question from the corner grid the
pre-M5 ``--logo-position`` used, and it is why this module exists rather than a
``LOGO_POSITIONS`` tuple in :mod:`~gpx_animate.domain.render_config`: there are
no corners any more, only points, and the two vocabularies are not
interchangeable.

The values are stated as *which side of the point the image body falls on*, not
in matplotlib's ``ha``/``va`` wording. The domain names no framework; the
renderer is the adapter that translates a side into an alignment.
"""

from __future__ import annotations


LOGO_ANCHORS: dict[str, tuple[str, str]] = {
    "center": ("center", "center"),
    "bottom": ("center", "above"),
    "top": ("center", "below"),
    "left": ("left", "center"),
    "right": ("right", "center"),
}
"""Anchor name to ``(side on x, side on y)``.

``side on x`` is one of ``left``, ``right``, ``center`` and says whether the
image lies to the left of the anchor point, to the right of it, or straddles
it. ``side on y`` is one of ``above``, ``below``, ``center`` and reads
vertically: ``above`` means the image sits over the point with its bottom edge
touching, which is what a marker pinned to the head of the line wants.
"""

DEFAULT_LOGO_ANCHOR = "center"
"""Anchor used when a logo is given as a bare path, so nothing in a registry
overrides it. ``center`` is the neutral choice: it is the only one that looks
the same at the start, the end and the head.
"""

DEFAULT_LOGO_SIZE_PX = 96
"""Width in pixels used when a logo is given as a bare path.

Width, not height and not the larger side, because that is what "a 48px logo"
conventionally means and because a logo's width is the dimension that reads at
a glance in a corner or beside a line. Height follows the image's own aspect
ratio, so a non-square file is never distorted. The size is in *device* pixels
of the rendered frame, so it scales with ``--dpi`` rather than with the
canvas: raising the dpi makes a finer video, not a bigger logo.
"""
