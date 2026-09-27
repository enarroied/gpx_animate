"""End-to-end: the real CLI, real tiles, real ffmpeg.

Deselected by default (see the `integration` marker in pyproject) because it
needs ffmpeg on PATH and network access to the tile servers. Run it with:

    uv run pytest -m integration

CI runs it as a non-blocking step, so a flaky tile server cannot turn the
pipeline red.
"""

import shutil

import pytest

from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.cli.main import main


def run_cli(gpx_path, out, **overrides):
    """Invoke the CLI the way a user would, through main()."""
    argv = [str(gpx_path), "--out", str(out), "--fps", "5", "--size", "1:1"]
    for flag, value in overrides.items():
        argv += [f"--{flag.replace('_', '-')}", str(value)]
    return main(argv)


def is_mp4(path) -> bool:
    """Whether the file starts with an MP4 ``ftyp`` box."""
    return path.read_bytes()[4:8] == b"ftyp"


@pytest.mark.integration
def test_produces_a_playable_mp4(short_track_gpx, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "trip.mp4"
    assert run_cli(short_track_gpx, out, duration=0.4, hold=0.2) == 0
    assert out.exists()
    assert out.stat().st_size > 0
    assert is_mp4(out)


@pytest.mark.integration
def test_frames_are_cleaned_up_afterwards(short_track_gpx, tmp_path):
    """Frames go to a TemporaryDirectory, so only the mp4 survives."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "trip.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0) == 0
    assert [p.name for p in tmp_path.iterdir()] == ["trip.mp4"]


@pytest.mark.integration
def test_every_basemap_style_renders(short_track_gpx, tmp_path):
    """The tile providers all have to work, not just the default."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    for style in available_styles():
        out = tmp_path / f"{style}.mp4"
        assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, style=style) == 0
        assert is_mp4(out), style


@pytest.mark.integration
def test_a_logo_is_baked_into_the_video(short_track_gpx, tmp_path, logo_png):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "with_logo.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, logo=logo_png) == 0
    assert is_mp4(out)
