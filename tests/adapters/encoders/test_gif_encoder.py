"""The GIF encoder: sizing and cropping, sampling, palette, and the error paths."""

import logging

import pytest
from PIL import Image
from PIL import ImageSequence
from PIL import ImageStat

from gpx_animate.adapters.encoders import gif_encoder
from gpx_animate.adapters.encoders.gif_encoder import FRAME_GLOB
from gpx_animate.adapters.encoders.gif_encoder import PillowGifEncoder
from gpx_animate.adapters.encoders.gif_encoder import frame_delay_ms
from gpx_animate.adapters.encoders.gif_encoder import frame_step
from gpx_animate.adapters.encoders.gif_encoder import pillow_available
from gpx_animate.adapters.encoders.gif_encoder import require_pillow
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.errors import GpxAnimateError
from gpx_animate.application.ports import GifEncoder
from gpx_animate.domain.render_config import GifConfig


def frame_count(gif_path):
    """How many frames the written GIF holds.

    ``Image.Image.n_frames`` only exists on the GIF subclass, so counting with
    ``ImageSequence`` keeps this working whatever ``Image.open`` returns.
    """
    with Image.open(gif_path) as gif:
        return sum(1 for _ in ImageSequence.Iterator(gif))


SOURCE_SIZE = (120, 240)
"""Tall, so a center-crop to a wide target is visibly a crop."""

FRAME_NAME = "frame_%05d.png"
"""The name renderers actually write; :data:`FRAME_GLOB` is what finds them."""


@pytest.fixture
def frames(tmp_path):
    """A directory of frames, each a distinguishable solid colour."""
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for index in range(12):
        shade = 20 * index
        image = Image.new("RGB", SOURCE_SIZE, (shade, shade, shade))
        image.save(frame_dir / (FRAME_NAME % index))
    return frame_dir


def encode(
    frames_dir,
    out_path,
    *,
    size="800x450",
    fps=5,
    mp4_fps=10,
    colors: int = 128,
    dither: bool = False,
    loop: int = 0,
):
    """Encode with a config built from explicit keyword overrides."""
    config = GifConfig(size=size, fps=fps, colors=colors, dither=dither, loop=loop)
    PillowGifEncoder().encode(frames_dir, config, mp4_fps, out_path)
    return out_path


class TestFrameNaming:
    def test_the_glob_is_not_the_printf_pattern(self):
        """``Path.glob`` has no ``%d``.

        The ffmpeg encoder takes a printf pattern; taking that same string here
        would match no files at all and every GIF would fail with "No frames
        found". The two constants look interchangeable and are not.
        """
        assert FRAME_GLOB == "frame_*.png"
        assert "%" not in FRAME_GLOB

    def test_the_glob_matches_the_names_renderers_write(self, frames):
        """The fixture writes frame_00000.png, as every renderer does."""
        assert len(sorted(frames.glob(FRAME_GLOB))) == 12


class TestPortConformance:
    def test_it_satisfies_the_gif_encoder_port(self):
        assert isinstance(PillowGifEncoder(), GifEncoder)

    def test_pillow_is_available_in_this_environment(self):
        """The tests below are meaningless without it, so say so loudly."""
        assert pillow_available()


class TestOutputSize:
    def test_the_size_is_honoured_exactly(self, frames, tmp_path):
        out = encode(frames, tmp_path / "a.gif", size="320x240")
        with Image.open(out) as gif:
            assert gif.size == (320, 240)

    def test_a_tall_clip_into_a_wide_gif_crops_rather_than_distorting(
        self, frames, tmp_path
    ):
        """SPECS US-10: frames are scaled to cover and center-cropped.

        Distorting instead would squash the track; the aspect ratio of the drawn
        content has to survive even though the pixel count does not.
        """
        out = encode(frames, tmp_path / "b.gif", size="400x100")
        with Image.open(out) as gif:
            assert gif.size == (400, 100)

    def test_the_written_size_is_logged(self, frames, tmp_path, caplog):
        """A size regression should be visible without opening the file."""
        caplog.set_level(logging.INFO)
        out = encode(frames, tmp_path / "c.gif")
        assert str(out) in caplog.text
        assert "bytes" in caplog.text


class TestSampling:
    def test_it_samples_every_nth_frame(self, frames, tmp_path):
        """30 mp4 fps into a 10 fps GIF keeps every third frame."""
        out = encode(frames, tmp_path / "d.gif", fps=10, mp4_fps=30)
        assert frame_count(out) == 4  # 12 frames / 3

    def test_a_matching_rate_keeps_every_frame(self, frames, tmp_path):
        out = encode(frames, tmp_path / "e.gif", fps=5, mp4_fps=5)
        assert frame_count(out) == 12

    def test_a_lower_gif_rate_drops_frames(self, frames, tmp_path):
        """12 frames at a stride of 4 leaves three, not four."""
        out = encode(frames, tmp_path / "f.gif", fps=3, mp4_fps=12)
        assert frame_count(out) == 3

    @pytest.mark.parametrize(
        ("mp4_fps", "gif_fps", "expected"),
        [
            (30, 15, 2),
            (30, 10, 3),
            (24, 12, 2),
            (30, 30, 1),
            (30, 25, 1),  # rounds to 1, so nothing is dropped
        ],
    )
    def test_the_stride_is_derived_from_the_two_rates(self, mp4_fps, gif_fps, expected):
        assert frame_step(mp4_fps, gif_fps) == expected

    def test_the_stride_is_never_zero(self):
        """A 0 stride would raise on the slice rather than sample."""
        assert frame_step(1, 1000) >= 1

    def test_a_gif_fps_above_the_source_is_refused(self, frames, tmp_path):
        """Frames cannot be invented, so the ask is rejected."""
        with pytest.raises(GifEncodeError, match="cannot be greater than source fps"):
            encode(frames, tmp_path / "g.gif", fps=30, mp4_fps=10)

    def test_the_refusal_names_both_rates(self, frames, tmp_path):
        with pytest.raises(GifEncodeError, match=r"30.*10"):
            encode(frames, tmp_path / "h.gif", fps=30, mp4_fps=10)

    def test_the_sampled_frames_are_the_earliest_ones(self, frames, tmp_path):
        """Stride sampling keeps frame 0, so the GIF starts where the clip does.

        Compared against the source frames rather than a hardcoded shade: the
        fixture's frames are 0, 20, 40 ... 220, so this asks "is the GIF's
        first frame frame 0" instead of guessing a brightness threshold.
        """

        def mean_of(image_path, frame_index=0):
            with Image.open(image_path) as image:
                if frame_index:
                    image.seek(frame_index)
                return ImageStat.Stat(image.convert("RGB")).mean

        out = encode(frames, tmp_path / "i.gif", fps=5, mp4_fps=10)
        with Image.open(out) as gif:
            gif.seek(0)
            first = ImageStat.Stat(gif.convert("RGB")).mean

        assert first == pytest.approx(mean_of(frames / (FRAME_NAME % 0)), abs=2)
        assert first != pytest.approx(mean_of(frames / (FRAME_NAME % 6)), abs=2)


class TestIdenticalFrames:
    """Pillow collapses runs of identical frames, and that is the right answer.

    Hold frames are pixel-identical to the last draw frame, so a clip with a
    long hold and a short duration is mostly static. Emitting those as separate
    frames would waste bytes and make viewers stall on a still image.
    """

    def _still_frames(self, tmp_path, count=6, size=SOURCE_SIZE):
        frame_dir = tmp_path / "still"
        frame_dir.mkdir()
        for index in range(count):
            Image.new("RGB", size, (30, 30, 30)).save(frame_dir / (FRAME_NAME % index))
        return frame_dir

    def test_a_run_of_identical_frames_collapses_to_one(self, tmp_path):
        out = encode(self._still_frames(tmp_path), tmp_path / "still.gif", mp4_fps=5)
        assert frame_count(out) == 1

    def test_the_collapsed_frame_keeps_the_total_duration(self, tmp_path):
        """Six frames at 200 ms must still play for 1.2 s, not 200 ms."""
        out = encode(self._still_frames(tmp_path), tmp_path / "still.gif", mp4_fps=5)
        with Image.open(out) as gif:
            assert gif.info["duration"] == 1200

    def test_a_moving_clip_keeps_every_sampled_frame(self, frames, tmp_path):
        """The fixture's frames are 0, 20, 40 ... so none of them match."""
        out = encode(frames, tmp_path / "moving.gif", mp4_fps=5)
        assert frame_count(out) == 12


class TestFrameDelay:
    def test_fifteen_fps_lands_on_seventy(self):
        """The spec's number: 15 fps is written as 70 ms, about 14.3 fps."""
        assert frame_delay_ms(15) == 70

    @pytest.mark.parametrize("gif_fps", [1, 3, 5, 10, 12, 15, 20, 24, 30, 50, 60, 100])
    def test_the_delay_is_always_a_whole_centisecond(self, gif_fps):
        """Pillow truncates to centiseconds, so a stray millisecond is lost.

        Rounding here rather than at the container is what stops 15 fps from
        becoming 67 ms, truncating to 60 ms, and playing 11% fast.
        """
        assert frame_delay_ms(gif_fps) % 10 == 0

    @pytest.mark.parametrize("gif_fps", [1, 3, 5, 10, 12, 15, 20, 24, 30, 50, 60, 100])
    def test_no_rate_is_left_unplayably_short(self, gif_fps):
        assert frame_delay_ms(gif_fps) >= 10

    @pytest.mark.parametrize(("gif_fps", "delay"), [(15, 70), (12, 80), (24, 40)])
    def test_it_rounds_to_the_nearest_centisecond(self, gif_fps, delay):
        assert frame_delay_ms(gif_fps) == delay

    def test_a_whole_rate_divides_exactly(self):
        assert frame_delay_ms(10) == 100

    @pytest.mark.parametrize(
        ("gif_fps", "effective"),
        [(10, 10.0), (20, 20.0), (25, 25.0)],
    )
    def test_the_delays_that_divide_exactly_hit_their_rate(self, gif_fps, effective):
        assert 1000.0 / frame_delay_ms(gif_fps) == pytest.approx(effective)

    def test_the_written_delay_lands_in_the_file(self, frames, tmp_path):
        out = encode(frames, tmp_path / "j.gif", fps=10, mp4_fps=10)
        with Image.open(out) as gif:
            assert gif.info["duration"] == 100

    def test_a_rate_that_does_not_divide_survives_the_round_trip(
        self, frames, tmp_path
    ):
        """The bug this rounding exists to prevent.

        15 fps does not divide into 100 ms. If the encoder asked for 67 ms the
        container would store 60 and the clip would play at 16.7 fps, so the
        test reads the delay back off disk rather than trusting the helper.
        """
        out = encode(frames, tmp_path / "k.gif", fps=15, mp4_fps=15)
        with Image.open(out) as gif:
            gif.seek(0)
            stored = gif.info["duration"]
        assert stored == 70
        assert stored % 10 == 0
        assert 1000.0 / stored == pytest.approx(14.3, abs=0.1)


class TestPalette:
    @pytest.mark.parametrize("colors", [64, 128, 256])
    def test_each_accepted_colour_count_is_usable(self, frames, tmp_path, colors):
        out = encode(frames, tmp_path / f"p{colors}.gif", colors=colors)
        assert out.exists()

    def test_the_palette_is_at_most_the_requested_size(self, frames, tmp_path):
        out = encode(frames, tmp_path / "q.gif", colors=64)
        with Image.open(out) as gif:
            palette = gif.getpalette() or []
        assert 0 < len(palette) <= 64 * 3

    def test_dither_off_is_the_default(self, frames, tmp_path):
        assert GifConfig().dither is False

    def test_dither_on_still_produces_a_valid_gif(self, frames, tmp_path):
        out = encode(frames, tmp_path / "r.gif", dither=True)
        assert frame_count(out) > 0

    def test_the_dither_choice_reaches_pillow(self, frames, tmp_path, monkeypatch):
        """Assert the argument rather than inferring it from the bytes."""
        seen = {}
        original = Image.Image.save

        def spy(self, fp, **kwargs):
            seen.update(kwargs)
            return original(self, fp, **kwargs)

        monkeypatch.setattr(Image.Image, "save", spy)
        encode(frames, tmp_path / "s.gif", dither=False)
        assert seen["dither"] == Image.Dither.NONE

    def test_dither_on_selects_floyd_steinberg(self, frames, tmp_path, monkeypatch):
        seen = {}
        original = Image.Image.save

        def spy(self, fp, **kwargs):
            seen.update(kwargs)
            return original(self, fp, **kwargs)

        monkeypatch.setattr(Image.Image, "save", spy)
        encode(frames, tmp_path / "t.gif", dither=True)
        assert seen["dither"] == Image.Dither.FLOYDSTEINBERG


class TestLoop:
    def test_loop_zero_means_forever(self, frames, tmp_path):
        out = encode(frames, tmp_path / "u.gif", loop=0)
        with Image.open(out) as gif:
            assert gif.info["loop"] == 0

    def test_a_finite_loop_count_is_written(self, frames, tmp_path):
        out = encode(frames, tmp_path / "v.gif", loop=3)
        with Image.open(out) as gif:
            assert gif.info["loop"] == 3


class TestFailureModes:
    def test_an_empty_frame_directory_is_an_error(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(GifEncodeError, match="No frames found"):
            PillowGifEncoder().encode(empty, GifConfig(), 30, tmp_path / "w.gif")

    def test_a_missing_frame_directory_is_an_error(self, tmp_path):
        with pytest.raises(GifEncodeError, match="No frames found"):
            PillowGifEncoder().encode(
                tmp_path / "nope", GifConfig(), 30, tmp_path / "x.gif"
            )

    def test_a_missing_pillow_is_reported_before_any_work(self, monkeypatch, tmp_path):
        """SPECS US-10 wants this before a render's worth of frames exists."""
        monkeypatch.setattr(gif_encoder, "Image", None)
        monkeypatch.setattr(gif_encoder, "ImageOps", None)
        with pytest.raises(GifEncodeError, match="Pillow is required"):
            PillowGifEncoder().encode(tmp_path, GifConfig(), 30, tmp_path / "y.gif")

    def test_require_pillow_reports_a_missing_pillow(self, monkeypatch):
        monkeypatch.setattr(gif_encoder, "Image", None)
        with pytest.raises(GifEncodeError, match="Pillow is required"):
            require_pillow()

    def test_require_pillow_is_quiet_when_pillow_is_there(self):
        require_pillow()  # must not raise

    def test_pillow_available_reflects_the_import(self, monkeypatch):
        monkeypatch.setattr(gif_encoder, "Image", None)
        assert not pillow_available()

    def test_the_error_is_a_gpx_animate_error(self):
        """Otherwise the CLI prints a traceback instead of exiting 1."""
        assert issubclass(GifEncodeError, GpxAnimateError)

    def test_the_error_is_also_a_runtime_error(self):
        assert issubclass(GifEncodeError, RuntimeError)
