"""Frozen entry point for the GUI.

The console script in pyproject.toml points at the same ``main``; PyInstaller
needs a real .py file to analyse, so the spec hands it this one.
"""

from gpx_animate.adapters.gui.main import main


if __name__ == "__main__":
    main()
