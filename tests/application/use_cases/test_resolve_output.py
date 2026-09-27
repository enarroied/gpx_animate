"""The resolve_output_path use case: naming, collisions, and --force."""

from datetime import datetime
from pathlib import Path

import pytest
from pytest import raises

from gpx_animate.application.use_cases import resolve_output as resolve_output_module
from gpx_animate.application.use_cases.resolve_output import OutputNameTakenError
from gpx_animate.application.use_cases.resolve_output import numbered_name
from gpx_animate.application.use_cases.resolve_output import resolve_output_path
from gpx_animate.application.use_cases.resolve_output import timestamped_name
from gpx_animate.domain.render_config import RenderConfig


STAMP = datetime(2026, 9, 27, 14, 2, 33)


class TestNames:
    def test_timestamped_name_carries_the_stem_and_the_time(self):
        assert timestamped_name(Path("trip.gpx"), STAMP) == "trip__20260927-140233.mp4"

    def test_timestamp_is_local_not_utc(self):
        """The spec's YYYYMMDD-HHMMSS reads as the creator's own clock."""
        assert timestamped_name(Path("t.gpx"), STAMP) == "t__20260927-140233.mp4"

    @pytest.mark.parametrize(
        ("name", "number", "expected"),
        [
            ("trip.mp4", 2, "trip__2.mp4"),
            ("trip.mp4", 17, "trip__17.mp4"),
            ("my.trip.gpx.mp4", 2, "my.trip.gpx__2.mp4"),
            ("no_suffix", 2, "no_suffix__2"),
        ],
    )
    def test_numbered_name_only_touches_the_extension(self, name, number, expected):
        assert numbered_name(Path(name), number) == Path(expected)

    def test_numbered_name_keeps_the_directory(self):
        assert numbered_name(Path("/a/b/trip.mp4"), 2) == Path("/a/b/trip__2.mp4")


class TestGeneratedName:
    def test_lands_in_the_output_dir(self):
        config = RenderConfig()
        assert resolve_output_path(config, Path("trip.gpx"), now=STAMP) == Path(
            "output/trip__20260927-140233.mp4"
        )

    def test_honours_a_custom_output_dir(self, tmp_path):
        config = RenderConfig(output_dir=tmp_path / "renders")
        assert resolve_output_path(config, Path("trip.gpx"), now=STAMP) == (
            tmp_path / "renders" / "trip__20260927-140233.mp4"
        )

    def test_does_not_depend_on_where_the_gpx_lives(self, tmp_path):
        """output_dir is resolved against the cwd, not the input's directory."""
        config = RenderConfig()
        result = resolve_output_path(config, tmp_path / "deep" / "trip.gpx", now=STAMP)
        assert result == Path("output/trip__20260927-140233.mp4")

    def test_creates_no_directories(self, tmp_path):
        """export_video owns directory creation; this only picks a name."""
        config = RenderConfig(output_dir=tmp_path / "made" / "up")
        assert resolve_output_path(config, Path("trip.gpx"), now=STAMP) == (
            tmp_path / "made" / "up" / "trip__20260927-140233.mp4"
        )
        assert not (tmp_path / "made").exists()

    def test_defaults_to_now_when_no_timestamp_is_given(self):
        """Only the shape is asserted; the clock is not ours to control."""
        result = resolve_output_path(RenderConfig(), Path("trip.gpx"))
        assert result.parent == Path("output")
        assert result.name.startswith("trip__")
        assert result.suffix == ".mp4"


class TestCollisionSuffixing:
    def test_explicit_out_is_honoured(self, tmp_path):
        config = RenderConfig(out=tmp_path / "chosen.mp4")
        assert resolve_output_path(config, Path("trip.gpx")) == tmp_path / "chosen.mp4"

    def test_an_existing_out_is_suffixed(self, tmp_path):
        out = tmp_path / "chosen.mp4"
        out.write_bytes(b"old")
        config = RenderConfig(out=out)
        assert (
            resolve_output_path(config, Path("trip.gpx")) == tmp_path / "chosen__2.mp4"
        )

    def test_the_counter_keeps_climbing(self, tmp_path):
        (tmp_path / "chosen.mp4").write_bytes(b"old")
        (tmp_path / "chosen__2.mp4").write_bytes(b"old")
        (tmp_path / "chosen__3.mp4").write_bytes(b"old")
        config = RenderConfig(out=tmp_path / "chosen.mp4")
        assert (
            resolve_output_path(config, Path("trip.gpx")) == tmp_path / "chosen__4.mp4"
        )

    def test_gaps_in_the_series_are_reused(self, tmp_path):
        """__2 is free even though __3 exists, so there is no need to skip it."""
        (tmp_path / "chosen.mp4").write_bytes(b"old")
        (tmp_path / "chosen__3.mp4").write_bytes(b"old")
        config = RenderConfig(out=tmp_path / "chosen.mp4")
        assert (
            resolve_output_path(config, Path("trip.gpx")) == tmp_path / "chosen__2.mp4"
        )

    def test_two_runs_in_the_same_second_do_not_collide(self, tmp_path):
        """The timestamp only has second resolution, so it is not enough alone."""
        config = RenderConfig(output_dir=tmp_path)
        first = resolve_output_path(config, Path("trip.gpx"), now=STAMP)
        first.write_bytes(b"first")
        second = resolve_output_path(config, Path("trip.gpx"), now=STAMP)
        assert first != second
        assert second.name == "trip__20260927-140233__2.mp4"

    def test_gives_up_instead_of_looping_forever(self, tmp_path, monkeypatch):
        monkeypatch.setattr(resolve_output_module, "MAX_COLLISION_ATTEMPTS", 2)
        (tmp_path / "chosen.mp4").write_bytes(b"old")
        (tmp_path / "chosen__2.mp4").write_bytes(b"old")
        (tmp_path / "chosen__3.mp4").write_bytes(b"old")
        config = RenderConfig(out=tmp_path / "chosen.mp4")
        with raises(OutputNameTakenError, match="alternatives"):
            resolve_output_path(config, Path("trip.gpx"))


class TestForce:
    def test_force_overwrites_an_explicit_out(self, tmp_path):
        out = tmp_path / "chosen.mp4"
        out.write_bytes(b"old")
        config = RenderConfig(out=out, force=True)
        assert resolve_output_path(config, Path("trip.gpx")) == out

    def test_force_keeps_an_existing_generated_name(self, tmp_path):
        """--force also covers two runs inside the same second."""
        config = RenderConfig(output_dir=tmp_path, force=True)
        taken = tmp_path / "trip__20260927-140233.mp4"
        taken.write_bytes(b"old")
        assert resolve_output_path(config, Path("trip.gpx"), now=STAMP) == taken

    def test_force_is_off_by_default(self):
        assert RenderConfig().force is False
