"""End-to-end: real render, real ffmpeg, real basemap tiles.

Deselected by default (see the `integration` marker in pyproject) because it
needs ffmpeg on PATH and network access to the tile servers. Run it with:

    uv run pytest -m integration

CI runs it as a non-blocking step, so a flaky tile server cannot turn the
pipeline red.
"""

import shutil
import sys

import pytest
from gpx_animate import main


@pytest.mark.integration
def test_produces_a_playable_mp4(short_track_gpx, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "trip.mp4"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpx_animate.py",
            str(short_track_gpx),
            "--duration",
            "0.4",
            "--hold",
            "0.2",
            "--fps",
            "5",
            "--size",
            "1:1",
            "--out",
            str(out),
        ],
    )

    main()

    assert out.exists()
    assert out.stat().st_size > 0
    # An MP4 container starts with a box whose type is "ftyp" at offset 4.
    assert out.read_bytes()[4:8] == b"ftyp"


@pytest.mark.integration
def test_frames_are_cleaned_up_afterwards(short_track_gpx, tmp_path, monkeypatch):
    """The temp dir is a TemporaryDirectory, so nothing survives the run."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")

    out = tmp_path / "trip.mp4"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpx_animate.py",
            str(short_track_gpx),
            "--duration",
            "0.2",
            "--fps",
            "5",
            "--out",
            str(out),
        ],
    )
    main()

    # Only the mp4 should be in tmp_path; frames went to a temp dir that is gone.
    assert [p.name for p in tmp_path.iterdir()] == ["trip.mp4"]
