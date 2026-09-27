"""gpx-animate — turn a GPX file into a short animated MP4.

Layering (SPECS section 3):

    domain       pure value types and geometry, no third-party framework
    application  use cases, plus the ports they depend on
    adapters     matplotlib, contextily, ffmpeg, gpxpy and the CLI

Importing this package gives you ``__version__`` and nothing else. Re-exporting
the adapters here would drag matplotlib into every ``import gpx_animate``,
which is precisely what the layering exists to prevent.
"""

__version__ = "0.0.0"
