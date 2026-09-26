"""The ffmpeg encode step: exact argv, and the missing-binary path.

Locking the argv down matters because these flags are the video quality
contract: CRF 18, yuv420p for browser playback, and the frame glob that
render_frames' filenames have to match.
"""

import subprocess

import gpx_animate
import pytest
from gpx_animate import frames_to_video


@pytest.fixture
def recorded_call(monkeypatch):
    """Capture the subprocess.run call instead of invoking ffmpeg."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(gpx_animate.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


class TestArgv:
    def test_builds_the_expected_command(self, recorded_call, tmp_path):
        out = tmp_path / "trip.mp4"
        frames_to_video(tmp_path, 30, out)
        cmd, _ = recorded_call[0]
        assert cmd == [
            "ffmpeg",
            "-y",
            "-framerate",
            "30",
            "-i",
            str(tmp_path / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-preset",
            "slow",
            str(out),
        ]

    def test_output_path_is_last(self, recorded_call, tmp_path):
        out = tmp_path / "final.mp4"
        frames_to_video(tmp_path, 24, out)
        cmd, _ = recorded_call[0]
        assert cmd[-1] == str(out)

    def test_frame_glob_matches_what_render_writes(self, recorded_call, tmp_path):
        """render_frames writes frame_00000.png, so the glob must be %05d."""
        frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
        cmd, _ = recorded_call[0]
        assert "frame_%05d.png" in cmd[cmd.index("-i") + 1]

    def test_quality_settings_are_stable(self, recorded_call, tmp_path):
        """These are the MP4 contract; a GIF feature must not change them."""
        frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
        cmd, _ = recorded_call[0]
        assert cmd[cmd.index("-crf") + 1] == "18"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
        assert cmd[cmd.index("-c:v") + 1] == "libx264"

    def test_failures_are_not_swallowed(self, recorded_call, tmp_path):
        frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
        _, kwargs = recorded_call[0]
        assert kwargs.get("check") is True

    def test_passes_exactly_one_call(self, recorded_call, tmp_path):
        frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
        assert len(recorded_call) == 1


class TestMissingFfmpeg:
    def test_exits_with_a_clear_message(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gpx_animate.shutil, "which", lambda name: None)
        with pytest.raises(SystemExit) as excinfo:
            frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
        assert "ffmpeg" in str(excinfo.value)

    def test_does_not_launch_anything(self, monkeypatch, tmp_path):
        def explode(*args, **kwargs):
            raise AssertionError("ffmpeg must not be invoked when it is absent")

        monkeypatch.setattr(gpx_animate.shutil, "which", lambda name: None)
        monkeypatch.setattr(subprocess, "run", explode)
        with pytest.raises(SystemExit):
            frames_to_video(tmp_path, 30, tmp_path / "x.mp4")
