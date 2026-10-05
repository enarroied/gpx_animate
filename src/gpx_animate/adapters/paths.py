"""Where the running program lives.

Two different questions, deliberately two different functions, because they
have different right answers and one overloaded helper would get one of them
wrong:

- :func:`application_dir` -- *find files that ship with the program.* An ffmpeg
  binary dropped next to the executable is the whole point of a portable
  install, and it belongs beside the program rather than on ``PATH``.

- :func:`output_dir_base` -- *decide where relative output lands.* This one must
  answer "wherever the user invoked me from", because that is the long-standing
  contract for a command-line tool, and a relative ``output/`` in the current
  directory is what every existing script and CI job already assumes.

The distinction matters because they disagree in exactly the case being fixed.
Double-clicking a frozen exe on Windows starts it with a working directory the
user never chose -- frequently ``C:\\Windows\\System32`` -- so a relative
``output/`` would write somewhere they will never look. Meanwhile ``argv[0]``
under ``uv run`` points into ``.venv/bin``, so using the program's own directory
for output would move every CLI render out from under its caller.
"""

from __future__ import annotations

import sys
from pathlib import Path


def application_dir() -> Path:
    """Directory holding the running program.

    For a frozen build that is the directory containing the executable, which
    is where anything shipped alongside it will be. For a source checkout it is
    the directory of the entry-point script, so a ``.bat`` sitting beside the
    project finds the files it put next to it.

    Returns:
        The directory, or the current directory if the program's location
        cannot be determined (embedded interpreters, ``python -c``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return Path.cwd()
    return Path(argv0).resolve().parent


def output_dir_base() -> Path:
    """Directory a relative output path is resolved against.

    Returns:
        The executable's directory for a frozen build, otherwise the current
        directory -- see the module docstring for why these differ.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resolve_output_dir(output_dir: Path) -> Path:
    """Rebase a relative output directory onto the program's own directory.

    A **no-op outside a frozen build**, and that is deliberate. Returning an
    absolute path there would change what the CLI prints and hands back for
    every existing script, CI job and test that reads a relative ``output/``,
    to fix a problem it does not have. The behaviour baseline exists precisely
    to catch that kind of well-meaning churn, so the change is confined to the
    case that is actually broken.

    Inside a frozen build it is the fix: a program double-clicked on Windows
    starts in a working directory the user did not choose, so ``output/``
    would resolve somewhere they have never looked and the finished video
    would appear to have been lost.

    An already-absolute path is returned untouched. A relative ``config.out`` is
    deliberately *not* routed through here: the user typed that path, and
    silently rebasing what someone explicitly asked for is worse than the
    ambiguity.

    Args:
        output_dir: The configured directory, relative or absolute.

    Returns:
        The directory to write into, absolute only when frozen.
    """
    path = Path(output_dir)
    if path.is_absolute() or not getattr(sys, "frozen", False):
        return path
    return output_dir_base() / path
