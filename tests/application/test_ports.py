"""The ports themselves: protocol conformance and the frame-numbering helper."""

import numpy as np
import pytest
from fakes import FakeBasemap
from fakes import FakeEncoder
from fakes import FakeLogoLoader
from fakes import FakeRenderer

from gpx_animate.adapters.basemaps.none import BlankBasemap
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.encoders.ffmpeg_encoder import FfmpegEncoder
from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.adapters.renderers.matplotlib_renderer import MatplotlibRenderer
from gpx_animate.application.ports import BasemapImage
from gpx_animate.application.ports import BasemapProvider
from gpx_animate.application.ports import Encoder
from gpx_animate.application.ports import FrameRenderer
from gpx_animate.application.ports import LogoLoader
from gpx_animate.application.ports import RenderResult
from gpx_animate.application.ports import frames_are_sequential
from gpx_animate.domain.bbox import Bbox


class TestFakesSatisfyThePorts:
    def test_fake_renderer_is_a_frame_renderer(self):
        assert isinstance(FakeRenderer(), FrameRenderer)

    def test_fake_encoder_is_an_encoder(self):
        assert isinstance(FakeEncoder(), Encoder)

    def test_fake_basemap_is_a_basemap_provider(self):
        assert isinstance(FakeBasemap(), BasemapProvider)

    def test_fake_logo_loader_is_a_logo_loader(self):
        assert isinstance(FakeLogoLoader(), LogoLoader)


class TestAdaptersSatisfyThePorts:
    def test_real_adapters_implement_the_same_contracts(self):
        assert isinstance(FfmpegEncoder(), Encoder)
        assert isinstance(BlankBasemap(), BasemapProvider)
        assert isinstance(TileBasemap(available_styles()[0]), BasemapProvider)
        assert isinstance(PngLogoLoader(), LogoLoader)
        assert isinstance(
            MatplotlibRenderer(BlankBasemap(), PngLogoLoader()), FrameRenderer
        )


class TestBasemapImage:
    def test_bbox_reorders_extent_into_west_south_east_north(self):
        image = BasemapImage(
            image=np.zeros((2, 2, 3)),
            extent=(-1.0, 1.0, -2.0, 2.0),
            crs="EPSG:3857",
        )
        assert image.bbox == Bbox(-1.0, -2.0, 1.0, 2.0)

    def test_attribution_defaults_to_none(self):
        image = BasemapImage(image=np.zeros((2, 2, 3)), extent=(0, 1, 0, 1), crs="x")
        assert image.attribution is None


class TestFramesAreSequential:
    def test_accepts_a_contiguous_run(self, tmp_path):
        paths = [tmp_path / f"frame_{i:05d}.png" for i in range(4)]
        assert frames_are_sequential(paths)

    def test_rejects_a_gap(self, tmp_path):
        paths = [tmp_path / f"frame_{i:05d}.png" for i in (0, 1, 3)]
        assert not frames_are_sequential(paths)

    def test_rejects_a_run_that_does_not_start_at_zero(self, tmp_path):
        paths = [tmp_path / f"frame_{i:05d}.png" for i in (1, 2)]
        assert not frames_are_sequential(paths)

    def test_rejects_the_wrong_numbering_width(self, tmp_path):
        """ffmpeg globs frame_%05d.png; frame_0.png would silently end the run."""
        assert not frames_are_sequential([tmp_path / "frame_0.png"])

    def test_no_frames_is_vacuously_sequential(self, tmp_path):
        assert frames_are_sequential([])


class TestRenderResult:
    def test_is_frozen(self, tmp_path):
        result = RenderResult(frame_dir=tmp_path, frame_paths=(), frame_count=0)
        with pytest.raises(AttributeError):
            result.frame_count = 5  # ty: ignore[invalid-assignment]
