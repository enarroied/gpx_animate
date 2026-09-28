"""The CLI adapter: argument wiring, precedence, and exit codes."""

import logging
import os
from pathlib import Path

import gpxpy.gpx
import pytest

from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.cli import main as cli
from gpx_animate.application.errors import FfmpegNotFoundError
from gpx_animate.application.ports import RenderResult
from gpx_animate.application.use_cases.render_animation import (
    render_animation as real_render_animation,
)
from gpx_animate.config import layers
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.render_config import RenderConfig


class Recorder:
    """Captures what the CLI hands the use cases instead of doing the work."""

    def __init__(self) -> None:
        self.configs: list[RenderConfig] = []
        self.rendered = 0
        self.encoded: list[tuple] = []
        self.raise_on_render: Exception | None = None

    def load(self, gpx_path):
        raise AssertionError("load_track should not be stubbed")

    def render(self, config, track, out_dir, renderer, logos=None):
        """Stand in for render_animation(config, track, out_dir, renderer)."""
        self.configs.append(config)
        if self.raise_on_render:
            raise self.raise_on_render
        self.rendered += 1

        return RenderResult(
            frame_dir=out_dir,
            frame_paths=tuple(
                out_dir / f"frame_{i:05d}.png" for i in range(config.n_frames)
            ),
            frame_count=config.n_frames,
        )

    def export(self, config, frames, encoder):
        """Stand in for export_video(config, frames, encoder)."""
        self.encoded.append((frames.frame_dir, config.fps, config.out))
        out = Path(config.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake video")
        return out


@pytest.fixture(autouse=True)
def hermetic_config(monkeypatch, tmp_path):
    """Keep the developer's own configuration out of these tests.

    ``main`` reads the real environment and the real ``~/.config``, so without
    this a stray ``GPX_ANIMATE_DURATION`` or a hand-written user TOML would
    change what the suite asserts. Every test also runs in a directory with no
    ``gpx-animate.toml`` in it, unless it writes one.
    """
    for name in list(os.environ):
        if name.startswith("GPX_ANIMATE_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(
        layers, "user_config_path", lambda: tmp_path / "no-such-user-config.toml"
    )
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def recorder(monkeypatch):
    """Stub out the two expensive use cases, leaving GPX loading real.

    load_track is deliberately not patched: it only reads a file, so it is fast
    and offline, and exercising it for real means the exit-code tests below
    trigger genuine errors instead of simulated ones.
    """
    recorder = Recorder()
    monkeypatch.setattr(cli, "render_animation", recorder.render)
    monkeypatch.setattr(cli, "export_video", recorder.export)
    return recorder


def run(*args: str) -> int:
    """Run the CLI with the given arguments."""
    return cli.main(list(args))


class TestSuccess:
    def test_returns_zero(self, recorder, short_track_gpx, tmp_path):
        assert run(str(short_track_gpx), "--out", str(tmp_path / "v.mp4")) == 0

    def test_writes_the_output(self, recorder, short_track_gpx, tmp_path):
        out = tmp_path / "v.mp4"
        run(str(short_track_gpx), "--out", str(out))
        assert out.exists()

    def test_renders_and_encodes_once(self, recorder, short_track_gpx, tmp_path):
        run(str(short_track_gpx), "--out", str(tmp_path / "v.mp4"))
        assert recorder.rendered == 1
        assert len(recorder.encoded) == 1

    def test_cleans_up_the_frame_directory(self, recorder, short_track_gpx, tmp_path):
        """The temporary directory must not survive the run."""
        run(str(short_track_gpx), "--out", str(tmp_path / "v.mp4"))
        frame_dir = recorder.encoded[0][0]
        assert not frame_dir.exists()

    def test_output_defaults_to_a_timestamped_name_in_output_dir(
        self, recorder, short_track_gpx, tmp_path, monkeypatch
    ):
        """SPECS US-4: ./output/<stem>__<YYYYMMDD-HHMMSS>.mp4, created on demand.

        The run happens in a temporary cwd so the test cannot leave an
        ``output/`` directory in the repository.
        """
        monkeypatch.chdir(tmp_path)
        gpx = tmp_path / "my_ride.gpx"
        gpx.write_bytes(short_track_gpx.read_bytes())
        run(str(gpx))
        out = recorder.encoded[0][2]
        assert out.parent == Path("output")
        assert out.stem.startswith("my_ride__")
        assert out.suffix == ".mp4"
        assert out.exists()

    def test_a_second_run_does_not_overwrite_the_first(
        self, recorder, short_track_gpx, tmp_path
    ):
        """Two runs in the same second must still produce two files."""
        out = tmp_path / "same.mp4"
        assert run(str(short_track_gpx), "--out", str(out)) == 0
        assert run(str(short_track_gpx), "--out", str(out)) == 0
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "same.mp4",
            "same__2.mp4",
        ]

    def test_frames_are_encoded_at_the_chosen_rate(
        self, recorder, short_track_gpx, tmp_path
    ):
        run(str(short_track_gpx), "--fps", "12", "--out", str(tmp_path / "v.mp4"))
        assert recorder.encoded[0][1] == 12


class TestDefaults:
    def test_uses_the_shipped_config_when_no_flags_are_given(
        self, recorder, short_track_gpx, tmp_path
    ):
        run(str(short_track_gpx), "--out", str(tmp_path / "v.mp4"))
        config = recorder.configs[0]
        assert config.style == default_config().style
        assert config.duration == default_config().duration
        assert config.fps == default_config().fps
        assert config.size == default_config().size


class TestFlagPrecedence:
    @pytest.mark.parametrize(
        ("flag", "value", "field", "expected"),
        [
            ("--style", "osm", "style", "osm"),
            ("--duration", "2.5", "duration", 2.5),
            ("--hold", "0.5", "hold", 0.5),
            ("--fps", "12", "fps", 12),
            ("--size", "9:16", "size", "9:16"),
            ("--margin", "0.4", "margin", 0.4),
            (
                "--bounds",
                "2.35,48.85,2.40,48.90",
                "bounds",
                Bbox(2.35, 48.85, 2.40, 48.90),
            ),
            ("--logo-start", "car", "logo_start", "car"),
            ("--logo-end", "/abs/x.png", "logo_end", "/abs/x.png"),
            ("--logo-marker", "walking_man", "logo_marker", "walking_man"),
        ],
    )
    def test_each_flag_reaches_the_config(
        self, recorder, short_track_gpx, tmp_path, flag, value, field, expected
    ):
        run(str(short_track_gpx), flag, value, "--out", str(tmp_path / "v.mp4"))
        assert getattr(recorder.configs[0], field) == expected

    def test_a_logo_source_stays_a_string(self, recorder, short_track_gpx, tmp_path):
        """A --logo-* value may be a registry name, so it is not a Path."""
        run(
            str(short_track_gpx),
            "--logo-start",
            "car",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        assert recorder.configs[0].logo_start == "car"

    def test_defaults_survive_when_only_one_flag_is_given(
        self, recorder, short_track_gpx, tmp_path
    ):
        """The old bug: a flag missing from a whitelist tuple was ignored."""
        run(str(short_track_gpx), "--fps", "12", "--out", str(tmp_path / "v.mp4"))
        assert recorder.configs[0].fps == 12
        assert recorder.configs[0].size == "16:9"

    def test_an_explicitly_passed_default_is_honoured(
        self, recorder, short_track_gpx, tmp_path
    ):
        """Passing --size 16:9 is indistinguishable from not passing it, and fine."""
        run(str(short_track_gpx), "--size", "16:9", "--out", str(tmp_path / "v.mp4"))
        assert recorder.configs[0].size == "16:9"


class TestParser:
    def test_every_flag_has_a_dest(self):
        dests = {
            action.dest
            for action in cli.build_parser()._actions
            if action.dest != "help"
        }
        assert dests == {
            "gpx",
            "style",
            "tiff",
            "duration",
            "hold",
            "fps",
            "size",
            "margin",
            "bounds",
            "out",
            "force",
            "logo_start",
            "logo_end",
            "logo_marker",
            "logo_registry",
            "log_level",
        }

    def test_style_choices_come_from_the_providers(self):
        parser = cli.build_parser()
        style_action = next(a for a in parser._actions if a.dest == "style")
        assert style_action.choices is not None
        assert tuple(style_action.choices) == style_choices()

    def test_style_offers_none_alongside_the_tiles(self):
        """--style none is a real option, not a gap in the tile catalogue."""
        assert style_choices() == (*available_styles(), "none")

    def test_size_choices_come_from_the_presets(self):
        parser = cli.build_parser()
        size_action = next(a for a in parser._actions if a.dest == "size")
        assert size_action.choices is not None
        assert set(size_action.choices) == set(SIZES)

    def test_log_level_defaults_to_info(self, short_track_gpx):
        assert cli.build_parser().parse_args([str(short_track_gpx)]).log_level == "INFO"

    def test_no_flag_is_required(self, short_track_gpx):
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        assert all(
            getattr(args, field) is None
            for field in (
                "style",
                "duration",
                "hold",
                "fps",
                "size",
                "margin",
                "out",
                "force",
            )
        )


class TestFailure:
    def test_an_unknown_style_is_rejected_by_argparse(self, short_track_gpx):
        with pytest.raises(SystemExit):
            run(str(short_track_gpx), "--style", "nope")

    def test_a_missing_file_exits_one(self, recorder, tmp_path):
        """A real OSError from load_track, not a simulated one."""
        assert run(str(tmp_path / "nope.gpx")) == 1

    def test_a_gpx_without_points_exits_one(self, recorder, waypoints_only_gpx):
        assert run(str(waypoints_only_gpx)) == 1

    def test_malformed_gpx_exits_one(self, recorder, malformed_gpx):
        """gpxpy's syntax error is not one of ours, so it keeps its traceback."""
        with pytest.raises(gpxpy.gpx.GPXXMLSyntaxException):
            run(str(malformed_gpx))

    def test_a_missing_ffmpeg_exits_one_without_a_traceback(
        self, recorder, short_track_gpx, tmp_path
    ):
        recorder.raise_on_render = FfmpegNotFoundError(
            "ffmpeg not found on PATH. Install it."
        )
        assert run(str(short_track_gpx), "--out", str(tmp_path / "v.mp4")) == 1

    def test_an_invalid_setting_exits_one(self, recorder, short_track_gpx, tmp_path):
        assert (
            run(str(short_track_gpx), "--fps", "0", "--out", str(tmp_path / "v.mp4"))
            == 1
        )

    def test_a_bad_bounds_exits_one_with_a_message(
        self, recorder, short_track_gpx, tmp_path, capsys
    ):
        rc = run(
            str(short_track_gpx),
            "--bounds",
            "2.35,91,2.40,92",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        out = capsys.readouterr()
        assert rc == 1
        assert "bounds" in out.out + out.err
        assert len(recorder.configs) == 0


class TestLogoResolution:
    """The real logo fail-fast, driven through main() with a fake renderer.

    The recorder fixture stubs render_animation, which is the point of the tests
    above; but the logo check lives *in* render_animation, so to see it here we
    restore the real one and stub the renderer instead — an image that is only
    ever constructed, never drawn.
    """

    @pytest.fixture
    def real_render(self, monkeypatch, tmp_path):
        fake = _FakeRenderer()

        def fake_encode(config, frames, encoder) -> Path:
            return config.out

        monkeypatch.setattr(cli, "render_animation", real_render_animation)
        monkeypatch.setattr(cli, "MatplotlibRenderer", lambda basemap, logos: fake)
        monkeypatch.setattr(cli, "export_video", fake_encode)
        return fake

    def test_a_missing_logo_exits_one_before_rendering(
        self, real_render, capsys, short_track_gpx, tmp_path
    ):
        rc = run(
            str(short_track_gpx),
            "--logo-start",
            "bogus",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        assert rc == 1
        assert real_render.calls == 0

    def test_a_missing_logo_mentions_the_registry_option(
        self, real_render, capsys, short_track_gpx, tmp_path
    ):
        run(
            str(short_track_gpx),
            "--logo-marker",
            "nope",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        out = capsys.readouterr()
        assert "--logo-registry" in out.out + out.err

    def test_a_registry_logo_resolves_and_renders(
        self, real_render, short_track_gpx, tmp_path, logo_png
    ):
        """A valid logo forges on: only the error paths fail early."""
        logos = tmp_path / "logos"
        logos.mkdir()
        (logos / "registry.yaml").write_text(
            "logos:\n  dot:\n    file: logo.png\n", encoding="utf-8"
        )
        (logos / "logo.png").write_bytes(logo_png.read_bytes())
        rc = run(
            str(short_track_gpx),
            "--logo-registry",
            str(logos / "registry.yaml"),
            "--logo-start",
            "dot",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        assert rc == 0
        assert real_render.calls == 1

    def test_a_path_to_a_valid_logo_resolves_too(
        self, real_render, short_track_gpx, tmp_path, logo_png
    ):
        """Bare paths are every bit as legal as registry names."""
        rc = run(
            str(short_track_gpx),
            "--logo-end",
            str(logo_png),
            "--out",
            str(tmp_path / "v.mp4"),
        )
        assert rc == 0
        assert real_render.calls == 1


class _FakeRenderer:
    """A renderer that merely records whether it was asked to draw."""

    def __init__(self) -> None:
        self.calls = 0

    def render(self, config, track, out_dir):
        self.calls += 1
        return RenderResult(frame_dir=out_dir, frame_paths=(), frame_count=0)


class TestConfigFromArgs:
    def test_returns_a_render_config(self, short_track_gpx):
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        assert isinstance(cli.config_from_args(args), RenderConfig)

    def test_leaves_the_destination_to_the_resolver(self, short_track_gpx):
        """config_from_args must not guess a name; resolve_output_path owns that."""
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        assert cli.config_from_args(args).out is None

    def test_force_is_applied(self, short_track_gpx):
        args = cli.build_parser().parse_args([str(short_track_gpx), "--force"])
        assert cli.config_from_args(args).force is True

    def test_bounds_are_parsed_into_a_box(self, short_track_gpx):
        args = cli.build_parser().parse_args(
            [str(short_track_gpx), "--bounds", "2.35,48.85,2.40,48.90"]
        )
        assert cli.config_from_args(args).bounds == Bbox(2.35, 48.85, 2.40, 48.90)

    def test_a_bad_bounds_value_raises_here(self, short_track_gpx):
        """config_from_args surfaces the parse error; main turns it into exit 1."""
        args = cli.build_parser().parse_args(
            [str(short_track_gpx), "--bounds", "1,2,3"]
        )
        with pytest.raises(ValueError, match="four numbers"):
            cli.config_from_args(args)

    def test_no_bounds_flag_keeps_the_base(self, short_track_gpx):
        base = RenderConfig(bounds=Bbox(1.0, 2.0, 3.0, 4.0))
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        assert cli.config_from_args(args, base).bounds == Bbox(1.0, 2.0, 3.0, 4.0)

    def test_force_keeps_the_layer_below_when_the_flag_is_absent(self, short_track_gpx):
        """store_true has to default to None, or a config file could not win."""
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        base = RenderConfig(force=True)
        assert cli.config_from_args(args, base).force is True

    def test_a_provided_base_is_used_instead_of_the_defaults(self, short_track_gpx):
        args = cli.build_parser().parse_args([str(short_track_gpx)])
        base = RenderConfig(style="osm", duration=9.0)
        assert cli.config_from_args(args, base) == base

    def test_does_not_mutate_the_defaults(self, short_track_gpx, tmp_path):
        cli.config_from_args(
            cli.build_parser().parse_args(
                [str(short_track_gpx), "--fps", "7", "--out", str(tmp_path / "v.mp4")]
            )
        )
        assert default_config().fps == 30


class TestLogging:
    def test_configures_the_root_logger(self, recorder, short_track_gpx, tmp_path):
        run(
            str(short_track_gpx),
            "--log-level",
            "DEBUG",
            "--out",
            str(tmp_path / "v.mp4"),
        )
        assert logging.getLogger().level == logging.DEBUG
        cli.configure_logging("INFO")

    def test_rejects_an_unknown_level(self, short_track_gpx):
        with pytest.raises(SystemExit):
            run(str(short_track_gpx), "--log-level", "TRACE")
