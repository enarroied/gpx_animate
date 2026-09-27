"""Decide where a render is written, without ever destroying an earlier one.

The naming rules are SPECS US-4: a generated name in ``output/`` carrying a
timestamp, and a numeric suffix when the name is already taken unless the run
was told to force. Resolution is separated from encoding because it has to
happen *before* the expensive render: a run that cannot write anywhere should
fail before drawing 150 frames.

No directory is created here. ``export_video`` owns that, and it does it with
``parents=True`` so ``--out some/where/x.mp4`` works too.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from gpx_animate.domain.render_config import RenderConfig


logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
"""Local time, e.g. ``20260927-140233``. Sortable, and filesystem-safe."""

MAX_COLLISION_ATTEMPTS = 1000
"""How many ``__2``, ``__3``, ... names to try before giving up."""


class OutputNameTakenError(ValueError):
    """Every candidate name in the collision series was already taken."""


def timestamped_name(gpx: Path, now: datetime) -> str:
    """Build the default filename for a track.

    Args:
        gpx: The input file, whose stem names the output.
        now: Timestamp to embed.

    Returns:
        A name like ``trip__20260927-140233.mp4``.
    """
    stamp = now.strftime(TIMESTAMP_FORMAT)
    return f"{gpx.stem}__{stamp}.mp4"


def numbered_name(path: Path, number: int) -> Path:
    """Insert a ``__N`` before the extension, keeping any other dots intact.

    ``trip.mp4`` becomes ``trip__2.mp4`` and ``my.trip.gpx.mp4`` becomes
    ``my.trip.gpx__2.mp4``; the last suffix is the extension, not the first dot.

    Args:
        path: The name that is already taken.
        number: The counter to insert. Only ``2`` and up are used.

    Returns:
        The alternative name.
    """
    return path.with_name(f"{path.stem}__{number}{path.suffix}")


def resolve_output_path(
    config: RenderConfig,
    gpx: Path,
    *,
    now: datetime | None = None,
) -> Path:
    """Pick the file this run writes to, never reusing an existing one.

    ``config.out`` wins when set. Otherwise the name is generated in
    ``config.output_dir`` as ``<gpx_stem>__<YYYYMMDD-HHMMSS>.mp4``. Either way,
    if that file exists and ``config.force`` is not set, the first free
    ``__2``, ``__3``, ... name is used instead.

    Args:
        config: Supplies ``out``, ``output_dir`` and ``force``.
        gpx: The input track, used for the stem.
        now: Timestamp for the generated name. Defaults to the current local
            time; injectable so the tests are not clock-dependent.

    Returns:
        A path that does not exist yet, unless ``force`` was set.

    Raises:
        OutputNameTakenError: If ``MAX_COLLISION_ATTEMPTS`` names are all taken.
    """
    if config.out is not None:
        candidate = Path(config.out)
    else:
        stamp = (now or datetime.now()).strftime(TIMESTAMP_FORMAT)
        candidate = config.output_dir / f"{gpx.stem}__{stamp}.mp4"

    if config.force or not candidate.exists():
        return candidate

    for number in range(2, MAX_COLLISION_ATTEMPTS + 2):
        alternative = numbered_name(candidate, number)
        if not alternative.exists():
            logger.info("%s exists, writing %s instead", candidate, alternative)
            return alternative

    raise OutputNameTakenError(
        f"{candidate} and its {MAX_COLLISION_ATTEMPTS} numbered alternatives all "
        "exist; delete some or pass --force"
    )
