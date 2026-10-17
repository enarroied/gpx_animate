"""Shaded relief: the pure arithmetic that turns elevations into light and shadow."""

import numpy as np
import pytest

from gpx_animate.domain.hillshade import MAX_LEVEL
from gpx_animate.domain.hillshade import MIN_LEVEL
from gpx_animate.domain.hillshade import blend
from gpx_animate.domain.hillshade import shade


class TestShade:
    def test_a_flat_grid_is_one_uniform_tone(self):
        """No gradient means no slope, so the whole surface faces straight up.

        The intensity is then simply sin(altitude), and the grid can carry no
        shape at all.
        """
        flat = np.full((5, 5), 1234.0)
        result = shade(flat, azimuth=315.0, altitude=45.0)
        assert result.shape == (5, 5)
        assert result.dtype == np.uint8
        assert len(set(result.ravel().tolist())) == 1
        expected = int(MIN_LEVEL + (MAX_LEVEL - MIN_LEVEL) * np.sin(np.radians(45.0)))
        assert result[0, 0] == expected

    def test_a_plane_rising_eastward_is_lit_from_the_west(self):
        """Analytic check: a 45-degree slope facing west catches western light.

        The plane rises toward the east, so its normal leans west. A light in
        the west (azimuth 270) meets it head-on and the intensity is exactly 1;
        the same light in the east (azimuth 90) grazes it and the intensity is
        exactly 0. Both can be read off by hand, so this pins the aspect sign,
        not just the shape of the output.
        """
        rows, cols = 6, 6
        plane = np.tile(np.arange(cols, dtype=float), (rows, 1))
        from_west = shade(plane, azimuth=270.0, altitude=45.0)
        from_east = shade(plane, azimuth=90.0, altitude=45.0)
        assert np.all(from_west == MAX_LEVEL)
        assert np.all(from_east == MIN_LEVEL)

    def test_z_factor_deepens_the_relief(self):
        """Exaggeration scales the gradient, so the same hill gains contrast."""
        ramp = np.tile(np.arange(8, dtype=float) * 0.1, (8, 1))
        gentle = shade(ramp, azimuth=270.0, z_factor=1.0)
        dramatic = shade(ramp, azimuth=270.0, z_factor=4.0)
        assert np.ptp(dramatic) >= np.ptp(gentle)
        assert not np.array_equal(gentle, dramatic)

    def test_output_is_always_within_the_byte_range(self):
        rng = np.random.default_rng(0)
        noisy = rng.normal(0.0, 500.0, size=(20, 20))
        result = shade(noisy, pixel_size_x=30.0, pixel_size_y=30.0)
        assert result.min() >= MIN_LEVEL
        assert result.max() <= MAX_LEVEL

    def test_it_rejects_a_non_two_dimensional_grid(self):
        with pytest.raises(ValueError, match="2-D"):
            shade(np.zeros(4))

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"pixel_size_x": 0.0}, "pixel sizes"),
            ({"pixel_size_y": -1.0}, "pixel sizes"),
            ({"z_factor": 0.0}, "z_factor"),
        ],
    )
    def test_it_rejects_impossible_parameters(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            shade(np.zeros((3, 3)), **kwargs)


class TestBlend:
    def test_full_strength_multiplies_the_colour(self):
        base = np.full((4, 6, 3), 255, dtype=np.uint8)
        shade_grid = shade(np.tile(np.arange(6, dtype=float), (4, 1)))
        result = blend(base, shade_grid, strength=1.0)
        assert result.shape == (4, 6, 3)
        assert result.dtype == np.uint8
        expected = (255 * (shade_grid.astype(float) / 255.0)).astype(np.uint8)
        assert np.array_equal(result[..., 0], expected)

    def test_zero_strength_leaves_the_map_untouched(self):
        base = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
        result = blend(base, np.array([[0, 255]]), strength=0.0)
        assert np.array_equal(result, base)

    def test_it_drops_alpha_from_the_base(self):
        base = np.full((2, 2, 4), 200, dtype=np.uint8)
        base[..., 3] = 7
        result = blend(base, np.full((2, 2), 128), strength=1.0)
        assert result.shape == (2, 2, 3)

    def test_it_clips_rather_than_wraps(self):
        base = np.full((2, 2, 3), 255, dtype=np.uint8)
        result = blend(base, np.full((2, 2), 255), strength=1.0)
        assert np.all(result == 255)

    def test_it_rejects_a_base_that_is_not_a_colour_image(self):
        with pytest.raises(ValueError, match="rows, cols, 3"):
            blend(np.zeros((4, 4)), np.zeros((4, 4)))

    def test_it_rejects_a_strength_outside_the_unit_range(self):
        with pytest.raises(ValueError, match="strength"):
            blend(np.zeros((2, 2, 3)), np.zeros((2, 2)), strength=1.5)
