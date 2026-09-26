"""Frame rendering, with contextily stubbed out so no tiles are downloaded.

contextily.add_basemap is the only reason a render needs the network, so
patching it makes the whole frame pipeline testable offline.
"""

import matplotlib


matplotlib.use("Agg")

import gpx_animate  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from gpx_animate import CONFIG  # noqa: E402
from gpx_animate import SIZES  # noqa: E402
from gpx_animate import render_frames  # noqa: E402


@pytest.fixture(autouse=True)
def no_tiles(monkeypatch):
    """Replace the basemap fetch with a no-op."""
    calls = []
    monkeypatch.setattr(
        gpx_animate.cx, "add_basemap", lambda ax, **kw: calls.append(kw)
    )
    return calls


@pytest.fixture
def track():
    """A short, gently climbing track: 6 points."""
    lons = np.array([7.00, 7.01, 7.02, 7.03, 7.04, 7.05])
    lats = np.array([45.00, 45.01, 45.00, 45.02, 45.01, 45.03])
    ele = np.array([100.0, 110.0, 105.0, 130.0, 125.0, 140.0])
    return lons, lats, ele


def fast_cfg(**overrides):
    """A CONFIG copy that renders a handful of frames at low resolution."""
    cfg = dict(CONFIG)
    cfg.update({"duration": 0.4, "hold": 0.2, "fps": 5, "dpi": 20})
    cfg.update(overrides)
    return cfg


def render(cfg, track, out_dir):
    """Call render_frames with an explicit signature.

    Unpacking the fixture with *track reads well but confuses ty's arity check.
    """
    lons, lats, ele = track
    return render_frames(cfg, lons, lats, ele, "Trip", out_dir)


class TestFrameMath:
    def test_frame_count_is_draw_plus_hold(self, track, tmp_path):
        cfg = fast_cfg(duration=1.0, hold=0.5, fps=4)  # 4 draw + 2 hold
        _, n_frames = render(cfg, track, tmp_path)
        assert n_frames == 6

    def test_truncation_can_shorten_the_clip(self, track, tmp_path):
        """int(duration*fps) truncates, so the clip may be shorter than asked."""
        cfg = fast_cfg(duration=0.19, hold=0.19, fps=5)  # int(0.95) = 0 each
        _, n_frames = render(cfg, track, tmp_path)
        assert n_frames == 0

    def test_frames_are_written_zero_padded_in_order(self, track, tmp_path):
        cfg = fast_cfg(duration=0.6, hold=0.2, fps=5)  # 3 + 1
        frame_paths, n_frames = render(cfg, track, tmp_path)
        assert n_frames == 4
        assert [p.name for p in frame_paths] == [
            "frame_00000.png",
            "frame_00001.png",
            "frame_00002.png",
            "frame_00003.png",
        ]
        assert all(p.exists() for p in frame_paths)

    def test_output_size_follows_size_and_dpi(self, track, tmp_path):
        cfg = fast_cfg(duration=0.4, hold=0.0, fps=5, size="1:1", dpi=20)
        frame_paths, _ = render(cfg, track, tmp_path)
        w, h = SIZES["1:1"]
        image = plt.imread(frame_paths[0])
        assert image.shape[:2] == (round(h * 20), round(w * 20))

    def test_hold_frames_are_identical_to_the_final_draw_frame(self, track, tmp_path):
        cfg = fast_cfg(duration=0.6, hold=0.6, fps=5)  # 3 draw + 3 hold
        frame_paths, n_frames = render(cfg, track, tmp_path)
        assert n_frames == 6
        final_draw = plt.imread(frame_paths[2])
        for path in frame_paths[3:]:
            assert np.array_equal(plt.imread(path), final_draw)

    def test_the_track_grows_between_early_frames(self, track, tmp_path):
        cfg = fast_cfg(duration=1.0, hold=0.0, fps=5)
        frame_paths, _ = render(cfg, track, tmp_path)
        first, last = plt.imread(frame_paths[0]), plt.imread(frame_paths[-1])
        assert not np.array_equal(first, last)


class TestBasemap:
    def test_add_basemap_is_called_once_with_the_configured_style(
        self, track, tmp_path, no_tiles
    ):
        render(fast_cfg(style="osm"), track, tmp_path)
        assert len(no_tiles) == 1
        assert no_tiles[0]["crs"] == "EPSG:3857"

    def test_a_user_agent_is_sent(self, track, tmp_path, no_tiles):
        """OSM's usage policy requires identifying the app."""
        render(fast_cfg(), track, tmp_path)
        assert "User-Agent" in no_tiles[0]["headers"]


class TestLogo:
    @pytest.mark.parametrize(
        "position", ["bottom-right", "bottom-left", "top-right", "top-left"]
    )
    def test_each_logo_position_renders(self, track, tmp_path, logo_png, position):
        cfg = fast_cfg(
            logo=logo_png, logo_position=position, duration=0.2, hold=0.0, fps=5
        )
        frame_paths, n_frames = render(cfg, track, tmp_path)
        assert n_frames == 1
        assert frame_paths[0].exists()

    def test_no_logo_by_default(self, track, tmp_path):
        cfg = fast_cfg()
        assert cfg["logo"] is None
        frame_paths, _ = render(cfg, track, tmp_path)
        assert frame_paths[0].exists()
