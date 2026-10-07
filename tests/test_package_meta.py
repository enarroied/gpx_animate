"""Package metadata: pyproject.toml is the single source of truth for the
version, and every other number must agree with it."""

from pathlib import Path

import tomllib

import gpx_animate


ROOT = Path(__file__).resolve().parents[1]


def test_the_package_version_matches_the_manifest():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert gpx_animate.__version__ == manifest["project"]["version"]
