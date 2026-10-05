"""The ffmpeg encoder: exact command line, and the missing-binary path."""

import subprocess

import pytest

from gpx_animate.adapters.encoders import ffmpeg_encoder
from gpx_animate.adapters.encoders.ffmpeg_encoder import CRF
from gpx_animate.adapters.encoders.ffmpeg_encoder import FRAME_GLOB
from gpx_animate.adapters.encoders.ffmpeg_encoder import YUV420P
from gpx_animate.adapters.encoders.ffmpeg_encoder import FfmpegEncoder
from gpx_animate.adapters.encoders.ffmpeg_encoder import build_command
from gpx_animate.adapters.encoders.ffmpeg_encoder import find_ffmpeg
from gpx_animate.application.errors import FfmpegNotFoundError


@pytest.fixture
def recorded_call(monkeypatch):
    """Capture the subprocess.run call instead of invoking ffmpeg."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


class TestCommandLine:
    def test_builds_the_expected_command(self, tmp_path):
        assert build_command(tmp_path, 30, tmp_path / "trip.mp4") == [
            "ffmpeg",
            "-y",
            "-framerate",
            "30",
            "-i",
            str(tmp_path / FRAME_GLOB),
            "-c:v",
            "libx264",
            "-pix_fmt",
            YUV420P,
            "-crf",
            CRF,
            "-preset",
            "slow",
            str(tmp_path / "trip.mp4"),
        ]

    def test_frame_glob_matches_what_the_renderer_writes(self, tmp_path):
        """MatplotlibRenderer writes frame_00000.png, so the glob must be %05d."""
        assert FRAME_GLOB == "frame_%05d.png"
        cmd = build_command(tmp_path, 30, tmp_path / "v.mp4")
        assert any(FRAME_GLOB in argument for argument in cmd)

    def test_quality_settings_are_stable(self, tmp_path):
        """The MP4 contract. The GIF encoder in M10 must not disturb it."""
        cmd = build_command(tmp_path, 30, tmp_path / "v.mp4")
        assert cmd[cmd.index("-crf") + 1] == "18"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        assert cmd[cmd.index("-preset") + 1] == "slow"

    def test_output_path_is_last(self, tmp_path):
        cmd = build_command(tmp_path, 24, tmp_path / "final.mp4")
        assert cmd[-1] == str(tmp_path / "final.mp4")

    def test_overwrites_without_asking(self, tmp_path):
        assert "-y" in build_command(tmp_path, 30, tmp_path / "v.mp4")


class TestEncoding:
    def test_runs_exactly_one_command(self, recorded_call, tmp_path):
        FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")
        assert len(recorded_call) == 1

    def test_failures_are_not_swallowed(self, recorded_call, tmp_path):
        FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")
        assert recorded_call[0][1].get("check") is True

    def test_passes_the_frame_rate_and_output_through(self, recorded_call, tmp_path):
        FfmpegEncoder().encode(tmp_path, 12, tmp_path / "v.mp4")
        cmd, _ = recorded_call[0]
        assert cmd[cmd.index("-framerate") + 1] == "12"
        assert cmd[-1] == str(tmp_path / "v.mp4")

    def test_a_non_zero_exit_raises(self, monkeypatch, tmp_path):
        def failing_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(subprocess, "run", failing_run)
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: "/usr/bin/x")
        with pytest.raises(subprocess.CalledProcessError):
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")


class TestMissingFfmpeg:
    def test_raises_a_dedicated_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: None)
        with pytest.raises(FfmpegNotFoundError, match="ffmpeg not found"):
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")

    def test_the_error_names_both_places_it_looked(self, monkeypatch, tmp_path):
        """A user who shipped the binary needs to be told it was not found
        *there*; telling them only about PATH sends them to install something
        they already have."""
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: None)
        with pytest.raises(FfmpegNotFoundError) as caught:
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")
        message = str(caught.value)
        assert "next to this program" in message
        assert "PATH" in message

    def test_does_not_launch_anything(self, monkeypatch, tmp_path):
        def explode(*args, **kwargs):
            raise AssertionError("ffmpeg must not run when it is absent")

        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: None)
        monkeypatch.setattr(subprocess, "run", explode)
        with pytest.raises(FfmpegNotFoundError):
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")

    def test_the_error_is_a_runtime_error(self, monkeypatch, tmp_path):
        """So a caller catching builtins still sees it."""
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError):
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")


class TestFindFfmpeg:
    """A portable install ships its own ffmpeg; PATH is the fallback."""

    @pytest.fixture
    def beside(self, monkeypatch, tmp_path):
        """Point the search at an empty directory next to 'the program'."""
        monkeypatch.setattr(ffmpeg_encoder, "application_dir", lambda: tmp_path)
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: "/usr/bin/x")
        return tmp_path

    def test_a_copy_beside_the_program_wins(self, beside):
        bundled = beside / "ffmpeg"
        bundled.write_text("#!/bin/sh\n")
        assert find_ffmpeg() == str(bundled)

    def test_it_beats_whichever_ffmpeg_is_on_path(self, beside):
        """Deliberate: a portable install encodes with the ffmpeg it shipped."""
        (beside / "ffmpeg").write_text("#!/bin/sh\n")
        assert find_ffmpeg() != "/usr/bin/x"

    def test_path_is_used_when_nothing_is_beside_it(self, beside):
        assert find_ffmpeg() == "/usr/bin/x"

    def test_the_windows_extension_is_tried_first(self, beside):
        """ffmpeg.exe cannot be run as `ffmpeg` on Windows."""
        (beside / "ffmpeg.exe").write_text("")
        (beside / "ffmpeg").write_text("")
        assert find_ffmpeg() == str(beside / "ffmpeg.exe")

    def test_the_bare_name_still_works(self, beside):
        (beside / "ffmpeg").write_text("")
        assert find_ffmpeg() == str(beside / "ffmpeg")

    def test_a_directory_named_ffmpeg_is_not_mistaken_for_the_binary(self, beside):
        """is_file(), not exists(): a stray directory must not become argv[0]."""
        (beside / "ffmpeg").mkdir()
        assert find_ffmpeg() == "/usr/bin/x"

    def test_none_when_there_is_no_ffmpeg_at_all(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ffmpeg_encoder, "application_dir", lambda: tmp_path)
        monkeypatch.setattr(ffmpeg_encoder.shutil, "which", lambda name: None)
        assert find_ffmpeg() is None


class TestExecutableIsInvoked:
    def test_the_resolved_path_is_what_runs(self, monkeypatch, tmp_path, recorded_call):
        bundled = tmp_path / "ffmpeg"
        bundled.write_text("#!/bin/sh\n")
        monkeypatch.setattr(ffmpeg_encoder, "application_dir", lambda: tmp_path)
        FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")
        assert recorded_call[0][0][0] == str(bundled)

    def test_build_command_defaults_to_the_bare_name(self, tmp_path):
        """Kept so the pinned command line is unchanged for PATH installs."""
        assert build_command(tmp_path, 30, tmp_path / "v.mp4")[0] == "ffmpeg"

    def test_build_command_accepts_an_explicit_executable(self, tmp_path):
        cmd = build_command(tmp_path, 30, tmp_path / "v.mp4", executable="/opt/ffmpeg")
        assert cmd[0] == "/opt/ffmpeg"
