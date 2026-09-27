"""The CLI adapter: argument wiring, precedence, and exit codes."""

import logging
from pathlib import Path

import gpxpy.gpx
import pytest

from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.adapters.cli import main as cli
from gpx_animate.application.errors import FfmpegNotFoundError
from gpx_animate.application.ports import RenderResult
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
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

    def render(self, config, track, out_dir, renderer):
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
            ("--logo-position", "top-left", "logo_position", "top-left"),
        ],
    )
    def test_each_flag_reaches_the_config(
        self, recorder, short_track_gpx, tmp_path, flag, value, field, expected
    ):
        run(str(short_track_gpx), flag, value, "--out", str(tmp_path / "v.mp4"))
        assert getattr(recorder.configs[0], field) == expected

    def test_out_and_logo_are_paths(self, recorder, short_track_gpx, tmp_path):
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"not really a png")
        out = tmp_path / "v.mp4"
        run(str(short_track_gpx), "--logo", str(logo), "--out", str(out))
        assert recorder.configs[0].logo == logo
        assert recorder.configs[0].out == out

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
            "duration",
            "hold",
            "fps",
            "size",
            "margin",
            "out",
            "force",
            "logo",
            "logo_position",
            "log_level",
        }

    def test_style_choices_come_from_the_providers(self):
        parser = cli.build_parser()
        style_action = next(a for a in parser._actions if a.dest == "style")
        assert style_action.choices is not None
        assert tuple(style_action.choices) == available_styles()

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
