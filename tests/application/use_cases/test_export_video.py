"""The export_video use case, driven through a fake encoder port."""

from fakes import FakeEncoder
from fakes import FakeRenderer
from pytest import raises

from gpx_animate.application.errors import FfmpegNotFoundError
from gpx_animate.application.use_cases.export_video import export_video
from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.domain.render_config import RenderConfig


class TestSuccess:
    def test_encodes_at_the_config_frame_rate(self, track, tmp_path):
        out = tmp_path / "trip.mp4"
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=out)
        frames = render_animation(config, track, tmp_path, FakeRenderer())
        encoder = FakeEncoder()
        assert export_video(config, frames, encoder) == out
        assert encoder.calls == [(tmp_path, 5, out)]

    def test_encodes_from_the_frames_own_directory(self, track, tmp_path):
        """The frame directory comes from the render, not from the config."""
        frame_dir = tmp_path / "frames"
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=tmp_path / "v.mp4")
        frames = render_animation(config, track, frame_dir, FakeRenderer())
        encoder = FakeEncoder()
        export_video(config, frames, encoder)
        assert encoder.calls[0][0] == frame_dir

    def test_creates_missing_output_directories(self, track, tmp_path):
        out = tmp_path / "nested" / "deeper" / "trip.mp4"
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=out)
        frames = render_animation(config, track, tmp_path, FakeRenderer())
        export_video(config, frames, FakeEncoder())
        assert out.exists()

    def test_overwrites_an_existing_output(self, track, tmp_path):
        out = tmp_path / "trip.mp4"
        out.write_bytes(b"stale")
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=out)
        frames = render_animation(config, track, tmp_path, FakeRenderer())
        export_video(config, frames, FakeEncoder())
        assert out.read_bytes() == b"fake video"


class TestFailure:
    def test_refuses_to_encode_without_a_destination(self, track, tmp_path):
        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=None)
        frames = render_animation(config, track, tmp_path, FakeRenderer())
        with raises(ValueError, match="out must be set"):
            export_video(config, frames, FakeEncoder())

    def test_encoder_failures_propagate_unchanged(self, track, tmp_path):
        """The use case must not swallow a missing ffmpeg into a success."""

        class BrokenEncoder:
            def encode(self, frame_dir, fps, out_path):
                raise FfmpegNotFoundError("ffmpeg not found on PATH. Install it.")

        config = RenderConfig(duration=0.2, hold=0.0, fps=5, out=tmp_path / "v.mp4")
        frames = render_animation(config, track, tmp_path, FakeRenderer())
        with raises(FfmpegNotFoundError):
            export_video(config, frames, BrokenEncoder())
