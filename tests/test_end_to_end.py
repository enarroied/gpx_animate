"""End-to-end: the real CLI, real tiles, real ffmpeg.

Deselected by default (see the `integration` marker in pyproject) because it
needs ffmpeg on PATH and network access to the tile servers. Run it with:

    uv run pytest -m integration

CI runs it as a non-blocking step, so a flaky tile server cannot turn the
pipeline red.
"""

import shutil

import contextily as cx
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
def test_the_default_output_dir_is_created(short_track_gpx, tmp_path, monkeypatch):
    """SPECS US-4 end to end: no --out means ./output/, created on demand."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    monkeypatch.chdir(tmp_path)
    assert (
        main([str(short_track_gpx), "--fps", "5", "--size", "1:1", "--duration", "0.2"])
        == 0
    )
    written = list((tmp_path / "output").iterdir())
    assert len(written) == 1
    assert written[0].name.startswith("short_track__")
    assert is_mp4(written[0])


@pytest.mark.integration
def test_a_logo_is_baked_into_the_video(short_track_gpx, tmp_path, logo_png):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "with_logo.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, logo=logo_png) == 0
    assert is_mp4(out)


@pytest.mark.integration
def test_style_none_renders_without_touching_the_network(
    short_track_gpx, tmp_path, monkeypatch
):
    """SPECS US-6: a render with no map at all, and no tile server involved."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    def explode(*args, **kwargs):
        raise AssertionError("--style none must not download tiles")

    monkeypatch.setattr(cx, "bounds2img", explode)
    out = tmp_path / "none.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, style="none") == 0
    assert is_mp4(out)


@pytest.mark.integration
def test_a_tiff_basemap_renders(short_track_gpx, tmp_path, track_tiff, monkeypatch):
    """SPECS US-6: bring your own GeoTIFF, and the video comes out of it."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    def explode(*args, **kwargs):
        raise AssertionError("--tiff must not download tiles")

    monkeypatch.setattr(cx, "bounds2img", explode)
    out = tmp_path / "tiff.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, tiff=track_tiff) == 0
    assert is_mp4(out)


@pytest.mark.integration
def test_a_missing_tiff_fails_before_rendering(short_track_gpx, tmp_path, capsys):
    """A bad --tiff path is a message and exit 1, not a traceback mid-render.

    The CLI configures logging onto stdout with force=True, which drops
    pytest's own handler, so this reads the printed message rather than using
    caplog.
    """
    out = tmp_path / "never.mp4"
    assert run_cli(short_track_gpx, out, duration=0.2, hold=0.0, tiff="nope.tif") == 1
    assert not out.exists()
    assert "no such GeoTIFF" in capsys.readouterr().out
