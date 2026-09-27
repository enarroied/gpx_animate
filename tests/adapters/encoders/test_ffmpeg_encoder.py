"""The ffmpeg encoder: exact command line, and the missing-binary path."""

import subprocess

import pytest

from gpx_animate.adapters.encoders import ffmpeg_encoder
from gpx_animate.adapters.encoders.ffmpeg_encoder import CRF
from gpx_animate.adapters.encoders.ffmpeg_encoder import FRAME_GLOB
from gpx_animate.adapters.encoders.ffmpeg_encoder import YUV420P
from gpx_animate.adapters.encoders.ffmpeg_encoder import FfmpegEncoder
from gpx_animate.adapters.encoders.ffmpeg_encoder import build_command
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
        with pytest.raises(FfmpegNotFoundError, match="ffmpeg not found on PATH"):
            FfmpegEncoder().encode(tmp_path, 30, tmp_path / "v.mp4")

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
