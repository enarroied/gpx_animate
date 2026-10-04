"""The export_video use case, driven through a fake encoder port."""

from dataclasses import replace

from fakes import FakeEncoder
from fakes import FakeGifEncoder
from fakes import FakeRenderer
from pytest import raises

from gpx_animate.application.errors import ChartFramesMissingError
from gpx_animate.application.errors import FfmpegNotFoundError
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.use_cases.export_video import export_video
from gpx_animate.application.use_cases.render_animation import render_animation
from gpx_animate.domain.render_config import GifConfig
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


def _render(config, track, tmp_path):
    """Render frames with the fake renderer, into a subdirectory of ``tmp_path``."""
    return render_animation(config, track, tmp_path, FakeRenderer())


class TestChartVideo:
    """US-11: the chart video is a sibling of the main one, from its own frames."""

    def _config(
        self,
        tmp_path,
        *,
        fps: int = 5,
        chart_video: bool = False,
        out=None,
    ):
        """A short config at an arbitrary rate; ``hold`` stays off.

        ``hold=0`` matters: the shipped default adds a second of hold, which
        would silently change every frame count asserted below.
        """
        return RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=fps,
            out=tmp_path / "trip.mp4" if out is None else out,
            chart_video=chart_video,
        )

    def test_no_chart_is_written_by_default(self, track, tmp_path):
        config = self._config(tmp_path)
        encoder = FakeEncoder()
        export_video(config, _render(config, track, tmp_path / "m"), encoder)
        assert [call[2].name for call in encoder.calls] == ["trip.mp4"]

    def test_the_sibling_shares_the_stem(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True)
        encoder = FakeEncoder()
        export_video(
            config,
            _render(config, track, tmp_path / "m"),
            encoder,
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert encoder.calls[1][2].name == "trip-chart.mp4"

    def test_the_sibling_keeps_the_suffix(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True, out=tmp_path / "trip.mkv")
        encoder = FakeEncoder()
        export_video(
            config,
            _render(config, track, tmp_path / "m"),
            encoder,
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert encoder.calls[1][2].name == "trip-chart.mkv"

    def test_an_existing_chart_is_overwritten_not_numbered(self, track, tmp_path):
        """The name is derived, so a second run does not produce trip-chart-2."""
        config = self._config(tmp_path, chart_video=True)
        for _ in range(2):
            encoder = FakeEncoder()
            export_video(
                config,
                _render(config, track, tmp_path / "m"),
                encoder,
                chart_frames=_render(config, track, tmp_path / "c"),
            )
        assert not (tmp_path / "trip-chart-2.mp4").exists()

    def test_it_is_written_after_the_main_video(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True)
        order: list = []
        export_video(
            config,
            _render(config, track, tmp_path / "m"),
            _NamedOrderEncoder(order),
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert order == ["trip.mp4", "trip-chart.mp4"]

    def test_the_chart_uses_its_own_frames(self, track, tmp_path):
        """The chart video is rendered separately, so it has its own directory."""
        config = self._config(tmp_path, chart_video=True)
        frames = _render(config, track, tmp_path / "m")
        charts = _render(config, track, tmp_path / "c")
        encoder = FakeEncoder()
        export_video(config, frames, encoder, chart_frames=charts)
        assert encoder.calls[0][0] != encoder.calls[1][0]

    def test_the_chart_shares_the_frame_rate(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True, fps=7)
        encoder = FakeEncoder()
        export_video(
            config,
            _render(config, track, tmp_path / "m"),
            encoder,
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert encoder.calls[1][1] == 7

    def test_missing_chart_frames_are_reported(self, track, tmp_path):
        """The flag is on but the CLI rendered none: a wiring mistake."""
        config = self._config(tmp_path, chart_video=True)
        with raises(ChartFramesMissingError, match="no chart frames"):
            export_video(config, _render(config, track, tmp_path / "m"), FakeEncoder())

    def test_the_main_video_survives_missing_chart_frames(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True)
        with raises(ChartFramesMissingError):
            export_video(config, _render(config, track, tmp_path / "m"), FakeEncoder())
        assert (tmp_path / "trip.mp4").exists()

    def test_the_return_value_is_still_the_main_video(self, track, tmp_path):
        config = self._config(tmp_path, chart_video=True)
        result = export_video(
            config,
            _render(config, track, tmp_path / "m"),
            FakeEncoder(),
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert result == tmp_path / "trip.mp4"


class _NamedOrderEncoder(FakeEncoder):
    """An MP4 encoder that records the name of each file it writes."""

    def __init__(self, order: list) -> None:
        super().__init__()
        self.order = order

    def encode(self, frame_dir, fps, out_path) -> None:
        self.order.append(out_path.name)
        super().encode(frame_dir, fps, out_path)


class _OrderedEncoder(FakeEncoder):
    """An MP4 encoder that notes when it ran, for ordering assertions."""

    def __init__(self, order: list) -> None:
        super().__init__()
        self.order = order

    def encode(self, frame_dir, fps, out_path) -> None:
        self.order.append("mp4")
        super().encode(frame_dir, fps, out_path)


class _OrderedGifEncoder(FakeGifEncoder):
    """A GIF encoder that notes when it ran, for ordering assertions."""

    def __init__(self, order: list) -> None:
        super().__init__()
        self.order = order

    def encode(self, frame_dir, config, mp4_fps, out_path) -> None:
        self.order.append("gif")
        super().encode(frame_dir, config, mp4_fps, out_path)


class TestGifOutput:
    """US-10: a GIF alongside the MP4, from the very same frames."""

    def _gif_config(self, tmp_path, *, enabled=True, out=None, colors: int = 128):
        """A config at 10 fps with the GIF on, and the GIF's own knobs."""
        config = RenderConfig(
            duration=0.2,
            hold=0.0,
            fps=10,
            out=tmp_path / "trip.mp4" if out is None else out,
        )
        return replace(config, gif=GifConfig(enabled=enabled, fps=5, colors=colors))

    def test_no_gif_is_written_when_disabled(self, track, tmp_path):
        config = self._gif_config(tmp_path, enabled=False)
        gif = FakeGifEncoder()
        export_video(
            config, _render(config, track, tmp_path), FakeEncoder(), gif_encoder=gif
        )
        assert gif.calls == []
        assert not (tmp_path / "trip.gif").exists()

    def test_a_gif_is_written_when_enabled(self, track, tmp_path):
        config = self._gif_config(tmp_path)
        export_video(
            config,
            _render(config, track, tmp_path),
            FakeEncoder(),
            gif_encoder=FakeGifEncoder(),
        )
        assert (tmp_path / "trip.gif").exists()

    def test_the_gif_is_always_dot_gif(self, track, tmp_path):
        """The GIF extension does not follow the video's suffix."""
        config = self._gif_config(tmp_path, out=tmp_path / "trip.mkv")
        export_video(
            config,
            _render(config, track, tmp_path),
            FakeEncoder(),
            gif_encoder=FakeGifEncoder(),
        )
        assert (tmp_path / "trip.gif").exists()

    def test_it_keeps_the_video_stem(self, track, tmp_path):
        config = self._gif_config(tmp_path, out=tmp_path / "ride-2026.mp4")
        gif = FakeGifEncoder()
        export_video(
            config, _render(config, track, tmp_path), FakeEncoder(), gif_encoder=gif
        )
        assert gif.calls[0][3].name == "ride-2026.gif"

    def test_it_encodes_from_the_same_frames_as_the_mp4(self, track, tmp_path):
        """A second render pass would cost more than the saving."""
        config = self._gif_config(tmp_path)
        frames = _render(config, track, tmp_path)
        encoder, gif = FakeEncoder(), FakeGifEncoder()
        export_video(config, frames, encoder, gif_encoder=gif)
        assert gif.calls[0][0] == encoder.calls[0][0]

    def test_it_is_given_the_source_frame_rate(self, track, tmp_path):
        """The encoder needs the MP4 rate to work out its sampling stride."""
        config = self._gif_config(tmp_path)
        gif = FakeGifEncoder()
        export_video(
            config, _render(config, track, tmp_path), FakeEncoder(), gif_encoder=gif
        )
        assert gif.calls[0][2] == config.fps

    def test_it_is_given_the_gif_config(self, track, tmp_path):
        config = self._gif_config(tmp_path, colors=64)
        gif = FakeGifEncoder()
        export_video(
            config, _render(config, track, tmp_path), FakeEncoder(), gif_encoder=gif
        )
        assert gif.calls[0][1] == config.gif
        assert gif.calls[0][1].colors == 64

    def test_the_mp4_encoder_arguments_are_unchanged(self, track, tmp_path):
        """The spec's explicit ask: enabling the GIF must not touch the MP4."""
        plain = self._gif_config(tmp_path, enabled=False, out=tmp_path / "a.mp4")
        with_gif = self._gif_config(tmp_path, enabled=True, out=tmp_path / "b.mp4")

        without = FakeEncoder()
        export_video(plain, _render(plain, track, tmp_path / "x"), without)
        after = FakeEncoder()
        export_video(
            with_gif,
            _render(with_gif, track, tmp_path / "y"),
            after,
            gif_encoder=FakeGifEncoder(),
        )

        assert without.calls[0][1] == after.calls[0][1]

    def test_the_gif_is_encoded_after_the_mp4(self, track, tmp_path):
        """The MP4 is the deliverable, so it is written first."""
        config = self._gif_config(tmp_path)
        order: list = []
        export_video(
            config,
            _render(config, track, tmp_path),
            _OrderedEncoder(order),
            gif_encoder=_OrderedGifEncoder(order),
        )
        assert order == ["mp4", "gif"]

    def test_a_missing_encoder_is_reported(self, track, tmp_path):
        """Wiring mistake: the flag is on but nothing was injected."""
        config = self._gif_config(tmp_path)
        with raises(GifEncodeError, match="no GIF encoder was provided"):
            export_video(config, _render(config, track, tmp_path), FakeEncoder())

    def test_the_mp4_survives_a_missing_encoder(self, track, tmp_path):
        config = self._gif_config(tmp_path)
        with raises(GifEncodeError):
            export_video(config, _render(config, track, tmp_path), FakeEncoder())
        assert (tmp_path / "trip.mp4").exists()

    def test_the_return_value_is_still_the_mp4(self, track, tmp_path):
        config = self._gif_config(tmp_path)
        result = export_video(
            config,
            _render(config, track, tmp_path),
            FakeEncoder(),
            gif_encoder=FakeGifEncoder(),
        )
        assert result == tmp_path / "trip.mp4"

    def test_the_chart_is_encoded_before_the_gif(self, track, tmp_path):
        """Output order is video, then chart, then GIF."""
        config = replace(self._gif_config(tmp_path), chart_video=True)
        order: list = []
        export_video(
            config,
            _render(config, track, tmp_path / "m"),
            _OrderedEncoder(order),
            gif_encoder=_OrderedGifEncoder(order),
            chart_frames=_render(config, track, tmp_path / "c"),
        )
        assert order == ["mp4", "mp4", "gif"]

    def test_all_three_outputs_from_one_render(self, track, tmp_path):
        config = replace(self._gif_config(tmp_path), chart_video=True)
        frames = _render(config, track, tmp_path / "m")
        charts = _render(config, track, tmp_path / "c")
        encoder, gif = FakeEncoder(), FakeGifEncoder()
        export_video(config, frames, encoder, gif_encoder=gif, chart_frames=charts)
        assert [call[2].name for call in encoder.calls] == [
            "trip.mp4",
            "trip-chart.mp4",
        ]
        assert gif.calls[0][3].name == "trip.gif"
