"""The PNG logo loader."""

import numpy as np
import pytest

from gpx_animate.adapters.logos.registry import PngLogoLoader
from gpx_animate.application.ports import LogoLoader


class TestLoading:
    def test_reads_an_image(self, logo_png):
        image = PngLogoLoader().load(str(logo_png))
        assert isinstance(image, np.ndarray)
        assert image.shape[:2] == (16, 16)

    def test_keeps_the_alpha_channel(self, logo_png):
        """A logo with transparency is the point; RGB-only would flatten it."""
        assert PngLogoLoader().load(str(logo_png)).shape[-1] == 4

    def test_is_normalised_for_imshow(self, logo_png):
        """matplotlib scales to 0..1 floats, and the renderer draws it directly."""
        image = PngLogoLoader().load(str(logo_png))
        assert image.min() >= 0.0
        assert image.max() <= 1.0

    def test_a_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PngLogoLoader().load(str(tmp_path / "nope.png"))

    def test_remembers_the_registry_directory(self, tmp_path):
        """Unused until M5 adds logos/registry.yaml, but the hook exists."""
        loader = PngLogoLoader(registry_dir=tmp_path)
        assert loader.registry_dir == tmp_path

    def test_the_registry_directory_is_optional(self):
        assert PngLogoLoader().registry_dir is None

    def test_satisfies_the_logo_port(self):

        assert isinstance(PngLogoLoader(), LogoLoader)
