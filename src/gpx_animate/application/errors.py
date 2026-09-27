"""Error types raised by the application layer.

All of them also subclass a builtin (``ValueError`` or ``RuntimeError``) so
that callers who only catch builtins keep working, and so tests can assert on
the builtin when the specific type does not matter.
"""

from __future__ import annotations


class GpxAnimateError(Exception):
    """Base class for every error this application raises deliberately."""


class NoPointsError(GpxAnimateError, ValueError):
    """The GPX file parsed, but held no track, route or waypoint points."""


class FfmpegNotFoundError(GpxAnimateError, RuntimeError):
    """ffmpeg is not on PATH, so the frames cannot be encoded."""
