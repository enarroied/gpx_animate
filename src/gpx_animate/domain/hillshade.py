"""Turning an elevation grid into a shaded-relief image, and blending it.

This is pure arithmetic on arrays, so it lives in the domain: no file is read,
no tile is fetched, no figure is drawn. The adapter that obtains the elevation
hands it over as numbers; this module only decides what light falling across
those numbers looks like.

The shading follows the convention every GIS uses (GDAL's ``gdaldem hillshade``,
ArcGIS, QGIS): a Lambertian surface lit from one direction, with slope taken
from the gradient of the elevation and the result scaled to 0-255. Because the
gradient is divided by the cell size, the caller must supply the cell size in
the *same unit as the elevations* -- metres for a metric grid. A DEM left in
degrees is the classic mistake: its horizontal spacing is not a length, so the
slopes come out nonsense.
"""

from __future__ import annotations

import numpy as np


MAX_LEVEL = 255
"""Brightest value a shaded pixel can take, the top of the output range."""

MIN_LEVEL = 1
"""Darkest value a shaded pixel can take. Never 0, so a fully shadowed slope
keeps a little detail rather than crushing to black."""

DEFAULT_AZIMUTH = 315.0
"""Light direction, degrees clockwise from north. From the north-west, the
cartographic default, which reads as the sun high over the left shoulder."""

DEFAULT_ALTITUDE = 45.0
"""Height of the light above the horizon, in degrees."""

DEFAULT_Z_FACTOR = 1.0
"""Vertical exaggeration. ``1.0`` is true relief; larger values dramatise it."""


def shade(
    elevation: np.ndarray,
    *,
    pixel_size_x: float = 1.0,
    pixel_size_y: float = 1.0,
    azimuth: float = DEFAULT_AZIMUTH,
    altitude: float = DEFAULT_ALTITUDE,
    z_factor: float = DEFAULT_Z_FACTOR,
) -> np.ndarray:
    """Shade an elevation grid as relief.

    Args:
        elevation: The elevations, as ``(rows, cols)``. Row 0 is the northern
            edge, matching the basemap convention, so the light comes from the
            top-left on screen.
        pixel_size_x: Ground distance between columns, in the same unit as
            ``elevation`` (metres for a metric grid).
        pixel_size_y: Ground distance between rows, same unit.
        azimuth: Light direction, degrees clockwise from north.
        altitude: Light elevation above the horizon, in degrees.
        z_factor: Vertical exaggeration, ``1.0`` for true relief.

    Returns:
        A ``(rows, cols)`` ``uint8`` array in ``1..255``.

    Raises:
        ValueError: If the grid is not two-dimensional, or a pixel size, the
            altitude or the z-factor is non-positive.
    """
    grid = np.asarray(elevation, dtype=float)
    if grid.ndim != 2:
        raise ValueError(f"elevation must be 2-D (rows, cols), got {grid.shape}")
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError(
            f"pixel sizes must be > 0, got {pixel_size_x} and {pixel_size_y}"
        )
    if z_factor <= 0:
        raise ValueError(f"z_factor must be > 0, got {z_factor}")

    # np.gradient returns the derivatives in axis order, so row 0 first: that is
    # dz/dy (north-south), then dz/dx (east-west). z_factor scales the gradient,
    # which is the same as scaling the elevations but avoids a second array.
    dz_dy, dz_dx = np.gradient(grid * z_factor, pixel_size_y, pixel_size_x)

    slope = np.pi / 2.0 - np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)

    light_azimuth = np.radians(azimuth % 360.0)
    light_altitude = np.radians(altitude)

    # Lamport illumination: the cosine between the surface normal and the light.
    # values below zero are slopes turned away from the light, i.e. shadow.
    intensity = np.sin(light_altitude) * np.sin(slope) + np.cos(
        light_altitude
    ) * np.cos(slope) * np.cos(light_azimuth - np.pi / 2.0 - aspect)
    intensity = np.clip(intensity, 0.0, 1.0)

    levels = MIN_LEVEL + (MAX_LEVEL - MIN_LEVEL) * intensity
    return levels.astype(np.uint8)


def blend(
    base_rgb: np.ndarray, shade_grid: np.ndarray, *, strength: float = 1.0
) -> np.ndarray:
    """Multiply a shade over a colour image to make it read as terrain.

    The colour image comes from a tile (OSM, topo) and the shade from
    :func:`shade`; multiplying darkens the map wherever the land faces away from
    the light and leaves it alone where it faces the light. That is the standard
    "terrain" look, and it is why a single-band shade has to be laid over colour
    rather than drawn alone.

    Args:
        base_rgb: The colour image, ``(rows, cols, 3)`` or ``(rows, cols, 4)``.
        shade_grid: The shade, ``(rows, cols)``, broadcast over the colour. It
            need not be the same size as ``base_rgb``; a ``(rows, cols)`` that
            matches, or broadcasts against, the colour's first two axes is fine.
        strength: How far toward the full multiply to go. ``0`` leaves the map
            untouched, ``1`` (the default) applies the whole shade.

    Returns:
        An ``(rows, cols, 3)`` ``uint8`` image. Any alpha in ``base_rgb`` is
        dropped: the result is opaque, which is what the renderer draws.

    Raises:
        ValueError: If ``base_rgb`` is not 3- or 4-channel, or ``strength`` is
            outside ``0..1``.
    """
    if strength < 0.0 or strength > 1.0:
        raise ValueError(f"strength must be in 0..1, got {strength}")
    colour = np.asarray(base_rgb, dtype=float)
    if colour.ndim != 3 or colour.shape[2] not in (3, 4):
        raise ValueError(
            f"base_rgb must be (rows, cols, 3) or (rows, cols, 4), got {colour.shape}"
        )
    rgb = colour[..., :3]
    factor = (
        1.0 - strength + strength * (np.asarray(shade_grid, dtype=float) / MAX_LEVEL)
    )
    blended = rgb * factor[..., np.newaxis]
    return np.clip(blended, 0.0, 255.0).astype(np.uint8)
