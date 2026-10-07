"""Frozen entry point for the CLI.

Built alongside the GUI so the frozen render path can be exercised end to end —
ffmpeg-beside-the-program, output-beside-the-exe — without driving a window.
See packaging/gpx-animate.spec.
"""

import sys

from gpx_animate.adapters.cli.main import main


if __name__ == "__main__":
    sys.exit(main())
