"""The composition root, which both front ends share.

These tests cover the module's own logic: the GIF preflight, the destination
resolution, and the ordering guarantees that let a failure be cheap. The
end-to-end wiring is already covered through ``cli.main`` in
``tests/adapters/cli/test_cli_main.py``, which drives this module for real.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fakes import FakeEncoder
from fakes import FakeGifEncoder

from gpx_animate.adapters import pipeline
from gpx_animate.adapters.encoders import gif_encoder as gif_encoder_module
from gpx_animate.adapters.encoders.gif_encoder import PillowGifEncoder
from gpx_animate.application.errors import GifEncodeError
from gpx_animate.application.ports import RenderResult
from gpx_animate.domain.render_config import RenderConfig


class TestBuildGifEncoder:
    """A GIF that cannot be encoded must be refused before anything is drawn."""

    def test_no_encoder_when_the_config_does_not_ask_for_one(self, fast_config):
        assert pipeline.build_gif_encoder(fast_config) is None

    def test_an_encoder_when_it_does(self, fast_config):
        config = dataclasses.replace(
            fast_config,
            gif=dataclasses.replace(fast_config.gif, enabled=True, fps=fast_config.fps),
        )
        assert isinstance(pipeline.build_gif_encoder(config), PillowGifEncoder)

    def test_a_missing_pillow_is_reported(self, fast_config, monkeypatch):
        """The check has to be the real one, so patch what require_pillow reads."""
        monkeypatch.setattr(gif_encoder_module, "Image", None)
        config = dataclasses.replace(
            fast_config,
            gif=dataclasses.replace(fast_config.gif, enabled=True, fps=fast_config.fps),
        )
        with pytest.raises(GifEncodeError, match="Pillow"):
            pipeline.build_gif_encoder(config)

    def test_a_missing_pillow_is_irrelevant_without_a_gif(
        self, fast_config, monkeypatch
    ):
        """Otherwise a missing optional dependency would break plain MP4 renders."""
        monkeypatch.setattr(gif_encoder_module, "Image", None)
        assert pipeline.build_gif_encoder(fast_config) is None

    def test_a_frame_rate_the_video_cannot_supply_is_refused(self, fast_config):
        config = dataclasses.replace(
            fast_config,
            fps=5,
            gif=dataclasses.replace(fast_config.gif, enabled=True, fps=15),
        )
        with pytest.raises(GifEncodeError, match="frames cannot be invented"):
            pipeline.build_gif_encoder(config)

    def test_a_frame_rate_equal_to_the_video_is_fine(self, fast_config):
        """The bound is 'greater than', not 'at least' -- 5 into 5 samples every frame."""
        config = dataclasses.replace(
            fast_config,
            fps=5,
            gif=dataclasses.replace(fast_config.gif, enabled=True, fps=5),
        )
        assert pipeline.build_gif_encoder(config) is not None


@pytest.fixture
def stub_render(monkeypatch, fast_config):
    """Replace the expensive parts, keeping the ordering they impose.

    Returns the list of frame directories the pipeline asked to be rendered, in
    order, so a test can assert *when* something happened rather than only that
    it did.
    """
    rendered: list[Path] = []

    def fake_render(config, track, out_dir, renderer, logos=None):
        rendered.append(Path(out_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        return RenderResult(
            frame_dir=Path(out_dir),
            frame_paths=tuple(
                Path(out_dir) / f"frame_{i:05d}.png" for i in range(config.n_frames)
            ),
            frame_count=config.n_frames,
        )

    monkeypatch.setattr(pipeline, "render_animation", fake_render)
    monkeypatch.setattr(pipeline, "FfmpegEncoder", FakeEncoder)
    monkeypatch.setattr(pipeline, "build_basemap", lambda config: object())
    monkeypatch.setattr(pipeline, "MatplotlibRenderer", lambda basemap, logos: object())
    monkeypatch.setattr(pipeline, "ProfileRenderer", object)
    return rendered


class TestRenderToVideo:
    def test_it_resolves_a_destination_the_caller_left_unset(
        self, stub_render, short_track_gpx, tmp_path, monkeypatch
    ):
        """config.out may be None; the pipeline is what turns that into a file.

        Forgetting this in a front end is exactly the bug the pipeline exists to
        prevent, so it is the pipeline's job.
        """
        monkeypatch.chdir(tmp_path)
        config = RenderConfig(
            style="none", duration=0.4, hold=0.2, fps=5, size="1:1", dpi=20
        )
        assert config.out is None

        out = pipeline.render_to_video(config, short_track_gpx)

        assert out.exists()
        # Relative, because output_dir defaults to a relative "output" and the
        # resolver does not absolutise it. Comparing resolved() would pass in
        # tmp_path and fail in the developer's own cwd.
        assert out.parent == Path("output")
        assert out.name.startswith(short_track_gpx.stem)

    def test_an_explicit_destination_is_honoured(
        self, stub_render, short_track_gpx, tmp_path
    ):
        out = tmp_path / "clip.mp4"
        config = RenderConfig(
            style="none", duration=0.4, hold=0.2, fps=5, size="1:1", dpi=20, out=out
        )
        assert pipeline.render_to_video(config, short_track_gpx) == out

    def test_the_frame_directory_does_not_survive_the_run(
        self, stub_render, short_track_gpx, tmp_path
    ):
        """The temp dir is owned here, so cleaning it up is this module's job."""
        config = RenderConfig(
            style="none",
            duration=0.4,
            hold=0.2,
            fps=5,
            size="1:1",
            dpi=20,
            out=tmp_path / "clip.mp4",
        )
        pipeline.render_to_video(config, short_track_gpx)
        assert stub_render, "expected a render to have happened"
        assert not any(d.exists() for d in stub_render)

    def test_a_chart_video_gets_its_own_render_pass(
        self, stub_render, short_track_gpx, tmp_path
    ):
        """Two videos means two renders: the chart is not carved out of the frames."""
        config = RenderConfig(
            style="none",
            duration=0.4,
            hold=0.2,
            fps=5,
            size="1:1",
            dpi=20,
            out=tmp_path / "clip.mp4",
            chart_video=True,
        )
        pipeline.render_to_video(config, short_track_gpx)

        assert len(stub_render) == 2
        assert (tmp_path / "clip-chart.mp4").exists()

    def test_no_chart_render_without_the_flag(
        self, stub_render, short_track_gpx, tmp_path
    ):
        config = RenderConfig(
            style="none",
            duration=0.4,
            hold=0.2,
            fps=5,
            size="1:1",
            dpi=20,
            out=tmp_path / "clip.mp4",
        )
        pipeline.render_to_video(config, short_track_gpx)

        assert len(stub_render) == 1
        assert not (tmp_path / "clip-chart.mp4").exists()

    def test_the_gif_preflight_happens_before_any_frame_is_drawn(
        self, stub_render, short_track_gpx, tmp_path, monkeypatch
    ):
        """The whole point of the preflight: no tiles spent to learn it cannot work.

        A GIF frame rate the video cannot supply is only discoverable from the
        config, so it costs nothing to catch -- but only if it is caught first.
        """
        monkeypatch.setattr(
            pipeline,
            "render_animation",
            lambda *a, **k: pytest.fail("rendered frames before the GIF preflight ran"),
        )
        config = RenderConfig(
            style="none",
            duration=0.4,
            hold=0.2,
            fps=5,
            size="1:1",
            dpi=20,
            out=tmp_path / "clip.mp4",
            gif=dataclasses.replace(RenderConfig().gif, enabled=True, fps=15),
        )
        with pytest.raises(GifEncodeError, match="frames cannot be invented"):
            pipeline.render_to_video(config, short_track_gpx)

    def test_the_gif_is_encoded_from_the_video_s_frames(
        self, stub_render, short_track_gpx, tmp_path, monkeypatch
    ):
        """One render, two outputs: the GIF must not trigger a second pass."""
        monkeypatch.setattr(
            pipeline, "build_gif_encoder", lambda config: FakeGifEncoder()
        )
        config = RenderConfig(
            style="none",
            duration=0.4,
            hold=0.2,
            fps=5,
            size="1:1",
            dpi=20,
            out=tmp_path / "clip.mp4",
            gif=dataclasses.replace(RenderConfig().gif, enabled=True, fps=5),
        )
        pipeline.render_to_video(config, short_track_gpx)

        assert len(stub_render) == 1
        assert (tmp_path / "clip.gif").exists()


def test_both_frame_sets_live_under_one_temporary_directory(
    monkeypatch, fast_config, track
):
    """A chart render used to write to a fixed /tmp/chart_frames.

    That leaked every frame of every chart render, and made two concurrent
    renders -- a CLI run and a GUI run, say -- share one directory. Both frame
    sets are now subdirectories of a single TemporaryDirectory, so cleanup is
    automatic and they cannot collide.
    """
    seen: dict[str, Path] = {}
    chart_config = dataclasses.replace(fast_config, chart_video=True)

    def fake_render(config, track, out_dir, renderer, logos=None):
        seen["dir"] = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return RenderResult(frame_dir=out_dir, frame_paths=(), frame_count=1)

    monkeypatch.setattr(pipeline, "load_track", lambda path: track)
    monkeypatch.setattr(pipeline, "render_animation", fake_render)
    monkeypatch.setattr(pipeline, "build_basemap", lambda config: object())
    monkeypatch.setattr(pipeline, "MatplotlibRenderer", lambda basemap, logos: object())
    monkeypatch.setattr(pipeline, "ProfileRenderer", object)
    monkeypatch.setattr(pipeline, "FfmpegEncoder", object)
    monkeypatch.setattr(pipeline, "build_gif_encoder", lambda config: None)
    monkeypatch.setattr(pipeline, "export_video", lambda *a, **k: Path("out.mp4"))

    pipeline.render_to_video(chart_config, Path("t.gpx"))

    # Both passes wrote below the same temporary root, and it is gone now.
    assert not seen["dir"].exists(), "the frame directory outlived the render"
    assert seen["dir"].name in {"frames", "chart"}


def test_the_chart_frame_directory_is_not_a_sibling_of_the_map_frames(
    monkeypatch, fast_config, track
):
    """The encoder globs non-recursively, so a subdirectory cannot be misread.

    If the map encoder ever saw the chart's PNGs as its own frames the output
    would be a video that alternated map and chart.
    """
    dirs: list[Path] = []

    def fake_render(config, track, out_dir, renderer, logos=None):
        dirs.append(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return RenderResult(frame_dir=out_dir, frame_paths=(), frame_count=1)

    monkeypatch.setattr(pipeline, "load_track", lambda path: track)
    monkeypatch.setattr(pipeline, "render_animation", fake_render)
    monkeypatch.setattr(pipeline, "build_basemap", lambda config: object())
    monkeypatch.setattr(pipeline, "MatplotlibRenderer", lambda basemap, logos: object())
    monkeypatch.setattr(pipeline, "ProfileRenderer", object)
    monkeypatch.setattr(pipeline, "FfmpegEncoder", object)
    monkeypatch.setattr(pipeline, "build_gif_encoder", lambda config: None)
    monkeypatch.setattr(pipeline, "export_video", lambda *a, **k: Path("out.mp4"))

    pipeline.render_to_video(
        dataclasses.replace(fast_config, chart_video=True), Path("t.gpx")
    )

    map_dir, chart_dir = dirs
    assert map_dir.name != chart_dir.name
    assert chart_dir.parent == map_dir.parent
    assert list(map_dir.glob(gif_encoder_module.FRAME_GLOB)) == []
