"""The bounding box, which every basemap provider and the renderer agree on."""

import numpy as np
import pytest

from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.bbox import parse_bounds
from gpx_animate.domain.bbox import validate_bounds


class TestRepr:
    def test_it_names_all_four_edges(self):
        assert repr(Bbox(1.0, 2.0, 3.0, 4.0)) == (
            "Bbox(min_x=1.0, min_y=2.0, max_x=3.0, max_y=4.0)"
        )

    def test_it_does_not_leak_numpy_scalars(self):
        """Boxes are built from numpy values, and these end up in user-facing text.

        ``numpy.float64`` subclasses ``float``, so the annotations are satisfied
        either way, but numpy 2 reprs as ``np.float64(1.0)``. A user told their
        GeoTIFF is in the wrong place should not have to read that.
        """
        box = Bbox(*(np.float64(v) for v in (1.0, 2.0, 3.0, 4.0)))
        assert "np.float64" not in repr(box)
        assert repr(box) == "Bbox(min_x=1.0, min_y=2.0, max_x=3.0, max_y=4.0)"


class TestMeasures:
    def test_width_is_east_minus_west(self):
        assert Bbox(0.0, -5.0, 10.0, 5.0).width == 10.0

    def test_height_is_north_minus_south(self):
        assert Bbox(0.0, -5.0, 10.0, 5.0).height == 10.0


class TestExtent:
    def test_is_left_right_bottom_top(self):
        """The order imshow wants, which is not the order Bbox stores."""
        assert Bbox(0.0, -5.0, 10.0, 5.0).extent == (0.0, 10.0, -5.0, 5.0)

    def test_round_trips_through_the_extent_convention(self):
        box = Bbox(-1.0, -2.0, 3.0, 4.0)
        left, right, bottom, top = box.extent
        assert Bbox(left, bottom, right, top) == box


class TestContains:
    def test_accepts_a_box_inside(self):
        assert Bbox(0.0, 0.0, 10.0, 10.0).contains(Bbox(2.0, 2.0, 8.0, 8.0))

    def test_accepts_itself(self):
        box = Bbox(0.0, 0.0, 10.0, 10.0)
        assert box.contains(box)

    def test_rejects_a_box_that_pokes_out(self):
        assert not Bbox(0.0, 0.0, 10.0, 10.0).contains(Bbox(-1.0, 2.0, 8.0, 8.0))


class TestOverlaps:
    def test_accepts_a_partial_overlap(self):
        assert Bbox(0.0, 0.0, 10.0, 10.0).overlaps(Bbox(5.0, 5.0, 15.0, 15.0))

    def test_accepts_full_containment_either_way(self):
        outer = Bbox(0.0, 0.0, 10.0, 10.0)
        assert outer.overlaps(Bbox(2.0, 2.0, 8.0, 8.0))
        assert Bbox(2.0, 2.0, 8.0, 8.0).overlaps(outer)

    def test_rejects_boxes_apart(self):
        assert not Bbox(0.0, 0.0, 10.0, 10.0).overlaps(Bbox(20.0, 20.0, 30.0, 30.0))

    def test_rejects_boxes_that_only_touch(self):
        """No pixel is shared, so a TIFF that butts up against the view is no use."""
        assert not Bbox(0.0, 0.0, 10.0, 10.0).overlaps(Bbox(10.0, 0.0, 20.0, 10.0))

    def test_a_degenerate_box_overlaps_what_contains_it(self):
        """A single-point track still sits somewhere, and its basemap is there."""
        point = Bbox(5.0, 5.0, 5.0, 5.0)
        assert point.overlaps(Bbox(0.0, 0.0, 10.0, 10.0))

    def test_two_degenerate_boxes_apart_do_not_overlap(self):
        assert not Bbox(5.0, 5.0, 5.0, 5.0).overlaps(Bbox(6.0, 6.0, 6.0, 6.0))


class TestPadded:
    def test_grows_by_a_fraction_of_each_axis(self):
        assert Bbox(0.0, 0.0, 10.0, 10.0).padded(0.15) == Bbox(-1.5, -1.5, 11.5, 11.5)

    def test_asymmetric_boxes_grow_symmetrically(self):
        """A 15% margin is 15% of the box, not of its distance from the origin."""
        assert Bbox(100.0, 200.0, 140.0, 260.0).padded(0.5) == Bbox(
            80.0, 170.0, 160.0, 290.0
        )

    def test_no_margin_still_gets_the_one_unit_floor(self):
        """--margin 0 means no *extra* padding; the floor is unconditional.

        That is what the renderer has always done, and the difference is a metre
        on a track measured in kilometres.
        """
        assert Bbox(0.0, 0.0, 10.0, 10.0).padded(0.0) == Bbox(-1.0, -1.0, 11.0, 11.0)

    def test_a_flat_axis_falls_back_to_one_unit(self):
        """A straight east-west track has no height; matplotlib cannot draw that."""
        padded = Bbox(0.0, 5.0, 10.0, 5.0).padded(0.0)
        assert (padded.min_y, padded.max_y) == (4.0, 6.0)

    def test_a_point_grows_on_every_side(self):
        assert Bbox(7.0, 45.0, 7.0, 45.0).padded(0.0) == Bbox(6.0, 44.0, 8.0, 46.0)

    def test_rejects_a_negative_margin(self):
        """RenderConfig rejects a negative margin, and so does this."""
        with pytest.raises(ValueError, match="fraction must be >= 0"):
            Bbox(0.0, 0.0, 10.0, 10.0).padded(-0.1)

    def test_padding_compounds(self):
        """Padding twice pads the padded box: 10 wide becomes 12, then 14.4."""
        once = Bbox(0.0, 0.0, 10.0, 10.0).padded(0.1)
        assert once.width == pytest.approx(12.0)
        assert once.padded(0.1).width == pytest.approx(14.4)


class TestParseBounds:
    """The ``--bounds`` "min_lon,min_lat,max_lon,max_lat" parsing and rejection."""

    def test_parses_four_numbers_into_a_box(self):
        assert parse_bounds("2.35,48.85,2.40,48.90") == Bbox(2.35, 48.85, 2.40, 48.90)

    def test_fractional_and_negative_degrees_are_fine(self):
        assert parse_bounds("-1.5,-0.25,2,3.5") == Bbox(-1.5, -0.25, 2.0, 3.5)

    def test_rejects_too_few_numbers(self):
        with pytest.raises(ValueError, match="four numbers"):
            parse_bounds("2.35,48.85,2.40")

    def test_rejects_too_many_numbers(self):
        with pytest.raises(ValueError, match="four numbers"):
            parse_bounds("1,2,3,4,5")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="four comma-separated numbers"):
            parse_bounds("a,b,c,d")

    def test_rejects_an_empty_string(self):
        with pytest.raises(ValueError, match="four comma-separated numbers"):
            parse_bounds("")

    def test_rejects_reversed_longitude(self):
        with pytest.raises(ValueError, match="min < max"):
            parse_bounds("2.40,48.85,2.35,48.90")

    def test_rejects_reversed_latitude(self):
        with pytest.raises(ValueError, match="min < max"):
            parse_bounds("2.35,48.90,2.40,48.85")

    def test_rejects_a_latitude_past_the_poles(self):
        with pytest.raises(ValueError, match="latitudes must be in"):
            parse_bounds("2.35,91,2.40,92")

    def test_rejects_a_longitude_past_the_antimeridian(self):
        with pytest.raises(ValueError, match="longitudes must be in"):
            parse_bounds("181,48.85,182,48.90")

    def test_an_edge_at_the_extreme_is_accepted(self):
        assert parse_bounds("-180,-90,180,90") == Bbox(-180.0, -90.0, 180.0, 90.0)


class TestValidateBounds:
    def test_accepts_a_sensible_window(self):
        validate_bounds(Bbox(2.35, 48.85, 2.40, 48.90))

    def test_rejects_an_unordered_edge(self):
        with pytest.raises(ValueError, match="min < max"):
            validate_bounds(Bbox(10.0, 0.0, -10.0, 5.0))
