"""GUI entry point — a stub until M8.

M8 builds the real PyQt window. It will be a second adapter over the same use
cases the CLI uses, with the widgets collecting the same
:class:`~gpx_animate.domain.render_config.RenderConfig`. Nothing here needs to
change in the application or domain layers for that to happen; that is the
point of the split.
"""

from __future__ import annotations


def main() -> int:
    """Explain that the GUI does not exist yet.

    Returns:
        A non-zero exit code.
    """
    raise NotImplementedError(
        "The PyQt GUI arrives in M8. Use the 'gpx-animate' CLI in the meantime."
    )
