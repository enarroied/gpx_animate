"""CONFIG, SIZES, STYLES, and the CONFIG-vs-CLI precedence rule.

The precedence tests drive the real main() with the render and encode steps
stubbed out, so they exercise the argument plumbing without touching the
network or ffmpeg.
"""

import copy
import sys
from pathlib import Path

import gpx_animate
import pytest
from gpx_animate import CONFIG
from gpx_animate import SIZES
from gpx_animate import STYLES
from gpx_animate import _carto
from gpx_animate import main


# Keys that CONFIG exposes but which have no CLI flag; changing them means
# editing CONFIG. Listed here so the day a flag appears, this test fails.
CONFIG_ONLY_KEYS = {
    "zoom_padding",
    "dpi",
    "bg_color",
    "track_faint",
    "track_bright",
    "marker_color",
    "hud_color",
    "title_color",
    "font",
}


@pytest.fixture
def captured_run(monkeypatch, short_track_gpx):
    """Run main() with rendering/encoding stubbed; return the cfg it assembled."""
    seen = {}

    def fake_render(cfg, lons, lats, ele, name, out_dir):
        seen["cfg"] = dict(cfg)
        seen["rendered"] = True
        return [], 1

    monkeypatch.setattr(gpx_animate, "render_frames", fake_render)
    monkeypatch.setattr(
        gpx_animate, "frames_to_video", lambda *a, **k: seen.update(encoded=True)
    )
    seen["gpx"] = short_track_gpx

    def run(*argv):
        monkeypatch.setattr(
            sys, "argv", ["gpx_animate.py", str(short_track_gpx), *argv]
        )
        main()
        return seen

    return run


class TestSizes:
    def test_exactly_the_three_documented_ratios(self):
        assert set(SIZES) == {"16:9", "1:1", "9:16"}

    def test_every_entry_is_a_width_height_pair(self):
        for name, (w, h) in SIZES.items():
            assert w > 0 and h > 0, name

    def test_portrait_and_landscape_are_oriented_correctly(self):
        assert SIZES["16:9"][0] > SIZES["16:9"][1]
        assert SIZES["9:16"][1] > SIZES["9:16"][0]
        assert SIZES["1:1"][0] == SIZES["1:1"][1]


class TestStyles:
    def test_key_free_providers_are_always_present(self):
        assert {"osm", "topo", "satellite"} <= set(STYLES)

    def test_no_style_is_none(self):
        """Carto entries are dropped at import time when no API key is set."""
        assert all(provider is not None for provider in STYLES.values())

    def test_carto_returns_none_without_a_key(self, monkeypatch):
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        assert _carto("https://example.com/{z}/{x}/{y}.png?key={key}") is None

    def test_carto_injects_the_key(self, monkeypatch):
        monkeypatch.setenv("CARTO_API_KEY", "secret123")
        provider = _carto("https://example.com/{z}/{x}/{y}.png?key={key}")
        assert provider["url"].endswith("key=secret123")
        assert provider["max_zoom"] == 20

    def test_carto_honours_a_custom_env_var(self, monkeypatch):
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        monkeypatch.setenv("OTHER_KEY", "abc")
        provider = _carto("https://x/{key}.png", key_env="OTHER_KEY")
        assert provider is not None
        assert provider["url"] == "https://x/abc.png"


class TestConfigIntegrity:
    def test_config_is_not_mutated_by_a_run(self, captured_run, short_track_gpx):
        """`cfg = dict(CONFIG)` is a copy; the module-level dict must survive."""
        before = copy.deepcopy(CONFIG)
        captured_run("--style", "osm", "--duration", "1.5", "--out", "/tmp/x.mp4")
        assert before == CONFIG

    def test_defaults_apply_when_no_flags_are_given(self, captured_run):
        cfg = captured_run("--out", "/tmp/x.mp4")["cfg"]
        assert cfg["style"] == CONFIG["style"]
        assert cfg["duration"] == CONFIG["duration"]
        assert cfg["hold"] == CONFIG["hold"]
        assert cfg["fps"] == CONFIG["fps"]
        assert cfg["size"] == CONFIG["size"]

    def test_documented_default_style_is_topo(self, captured_run):
        """README 4 claims `positron`; the code says otherwise. Trust the code."""
        assert CONFIG["style"] == "topo"
        assert captured_run("--out", "/tmp/x.mp4")["cfg"]["style"] == "topo"


class TestCliPrecedence:
    @pytest.mark.parametrize(
        ("flag", "value", "key"),
        [
            ("--style", "osm", "style"),
            ("--duration", "2.5", "duration"),
            ("--hold", "0.5", "hold"),
            ("--fps", "12", "fps"),
            ("--size", "9:16", "size"),
            ("--logo-position", "top-left", "logo_position"),
        ],
    )
    def test_flag_overrides_config(self, captured_run, flag, value, key):
        cfg = captured_run(flag, value, "--out", "/tmp/x.mp4")["cfg"]
        assert cfg[key] != CONFIG[key], "flag did not win over CONFIG"
        assert str(cfg[key]) == value

    def test_out_defaults_to_the_gpx_path(self, captured_run, short_track_gpx):
        cfg = captured_run()["cfg"]
        assert Path(cfg["out"]) == short_track_gpx.with_suffix(".mp4")

    def test_explicit_out_wins(self, captured_run, tmp_path):
        target = tmp_path / "custom.mp4"
        cfg = captured_run("--out", str(target))["cfg"]
        assert Path(cfg["out"]) == target

    def test_every_flag_with_a_config_key_is_wired_up(self, captured_run):
        """Regression guard for the whitelist tuple in main().

        A flag added to parse_args() but not to that tuple is silently ignored,
        so every CONFIG-backed flag is applied and compared against the default.
        """
        values = {
            "style": "osm",
            "duration": "2.5",
            "hold": "0.5",
            "fps": "12",
            "size": "1:1",
            "logo_position": "top-right",
        }
        cfg = captured_run(*_flatten(values.items()), "--out", "/tmp/x.mp4")["cfg"]
        for key, value in values.items():
            assert str(cfg[key]) == value, f"--{key.replace('_', '-')} is not applied"

    def test_logo_flag_is_optional(self, captured_run, logo_png):
        cfg = captured_run("--logo", str(logo_png), "--out", "/tmp/x.mp4")["cfg"]
        assert Path(cfg["logo"]) == logo_png

    def test_config_only_keys_really_have_no_flags(self, monkeypatch):
        """No argparse destination exists for any CONFIG-only key."""
        monkeypatch.setattr(sys, "argv", ["gpx_animate.py", "trip.gpx"])
        dests = set(vars(gpx_animate.parse_args()))
        assert not CONFIG_ONLY_KEYS & dests

    def test_encode_step_runs_after_render(self, captured_run):
        seen = captured_run("--out", "/tmp/x.mp4")
        assert seen.get("rendered") and seen.get("encoded")


def _flatten(items):
    out = []
    for key, value in items:
        out.extend([f"--{key.replace('_', '-')}", value])
    return out
