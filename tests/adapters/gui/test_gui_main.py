"""The GUI adapter: every config field, and the claims the architecture makes.

The tests here are mostly about two things. First, that the GUI is a *peer* of
the CLI rather than a front end for it: the ``render_to_video`` identity test
below is the one that would fail if someone ever made this module shell out or
re-wire rendering. Second, that no ``RenderConfig`` field is unreachable from
the widgets, because "the GUI can do everything the CLI can" is a promise that
rots quietly the moment a flag is added and a spinbox is not.
"""

import ast
import dataclasses
import inspect
import logging
import os
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

import pytest
import tomllib
from PyQt6 import sip
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QColorDialog
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QTabWidget

from gpx_animate.adapters import gui as gui_package
from gpx_animate.adapters import pipeline
from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.cli import main as cli_main
from gpx_animate.adapters.gui import main as gui_main
from gpx_animate.adapters.gui.main import STYLE_COLORS
from gpx_animate.adapters.gui.main import MainWindow
from gpx_animate.adapters.gui.main import RenderWorker
from gpx_animate.adapters.gui.main import _LogBridge
from gpx_animate.adapters.gui.main import _optional_bounds
from gpx_animate.adapters.gui.main import _PaneEmitter
from gpx_animate.adapters.gui.main import config_from_widgets
from gpx_animate.adapters.gui.main import main as gui_entry_point
from gpx_animate.application.errors import NoPointsError
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.defaults import default_config
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.render_config import PROFILE_POSITIONS
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import Style


CONFIG_FIELDS = [f.name for f in dataclasses.fields(RenderConfig)]
"""Derived, so a field added to the domain is automatically covered here."""


@pytest.fixture
def base() -> RenderConfig:
    """A default config to seed a window with."""
    return default_config()


@pytest.fixture
def window(qtbot, base, request):
    """A window with defaults, hermetically loaded.

    ``hermetic_config`` is pulled in with ``getfixturevalue`` rather than as a
    parameter because it is wanted for its side effects only -- it returns
    nothing, and binding it to a name would look like an unused argument to
    vulture, which cannot see that requesting a fixture is the use.
    """
    request.getfixturevalue("hermetic_config")
    win = MainWindow(base=base)
    qtbot.addWidget(win)
    return win


# --- the two-front-ends contract -------------------------------------------


def test_the_gui_and_the_cli_share_one_render_function():
    """The load-bearing test of this whole change.

    If the GUI ever grew its own rendering path, this would still import and
    still pass most of the suite. Comparing the *function objects* is what makes
    "one composition root, two front ends" a fact rather than an intention.
    """
    assert gui_main.render_to_video is pipeline.render_to_video
    assert gui_main.render_to_video is cli_main.render_to_video


def test_the_gui_never_shells_out_to_the_cli():
    """A GUI that ran ``gpx-animate`` in a subprocess would be a wrapper, not a peer.

    Parsed rather than grepped, because this module's own docstring explains why
    it does *not* use ``QProcess`` -- a substring scan would match the
    explanation and fail on the correct code. Walking the tree also catches the
    indirect forms (``os.system``, ``runpy``, a re-exported helper) that a scan
    for one obvious name would miss.
    """
    imported = _module_level_imports(Path(gui_main.__file__))
    banned = {"subprocess", "runpy", "commands", "pty", "shlex", "QProcess"}
    assert not banned & set(imported), imported
    assert not _calls_named(
        Path(gui_main.__file__), {"system", "popen", "spawn", "Popen"}
    )


def _module_level_imports(path: Path) -> set[str]:
    """Top-level module names imported anywhere in ``path``, from its AST."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _calls_named(path: Path, methods: set[str]) -> bool:
    """Whether ``path`` calls any of ``methods``, at any depth."""
    tree = ast.parse(path.read_text())
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in methods
        for node in ast.walk(tree)
    )


def test_the_cli_stays_free_of_qt():
    """PyQt6 is an optional extra, so nothing on the CLI's import path may touch it.

    A ``PyQt6`` import anywhere under the CLI, pipeline or application layers
    would make ``uvx gpx-animate`` fail on a machine without the extra, which is
    the entire reason the GUI is optional.
    """
    package = Path(gui_main.__file__).parents[2]
    for relative in (
        "adapters/cli/main.py",
        "adapters/pipeline.py",
        "application/use_cases/render_animation.py",
        "application/use_cases/export_video.py",
        "config/loader.py",
    ):
        imported = _module_level_imports(package / relative)
        assert "PyQt6" not in imported, relative


def test_the_gui_is_an_optional_extra_rather_than_a_dependency():
    """``uv sync`` without ``--extra gui`` must not pull Qt in.

    Reads pyproject through tomllib rather than importing it, so this asserts
    about the manifest a user ships rather than about whatever a re-lock did.
    """
    manifest = tomllib.loads(
        (Path(gui_main.__file__).parents[4] / "pyproject.toml").read_text()
    )
    extras = manifest["project"].get("optional-dependencies", {})
    assert any("pyqt6" in dep.lower() for dep in extras.get("gui", []))
    assert not any(
        "pyqt6" in dep.lower() for dep in manifest["project"]["dependencies"]
    )
    assert (
        manifest["project"]["scripts"]["gpx-animate-gui"]
        == "gpx_animate.adapters.gui.main:main"
    )
    # The CLI script must survive the GUI landing.
    assert (
        manifest["project"]["scripts"]["gpx-animate"]
        == "gpx_animate.adapters.cli.main:main"
    )


def test_the_cli_still_runs_in_a_process_with_no_pyqt_installed():
    """Prove the optionality, rather than asserting it from the manifest.

    ``--version``-style import of the CLI under a stubbed-out ``PyQt6`` proves no
    import in its chain reaches for Qt. Real isolation would need a separate
    venv per run, which is what the extra itself is for.
    """
    script = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name == 'PyQt6' or name.startswith('PyQt6.') else None\n"
        "    def load_module(self, name):\n"
        "        raise ImportError('PyQt6 is blocked')\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "from gpx_animate.adapters.cli import main\n"
        "assert 'PyQt6' not in sys.modules\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# --- every field is reachable ---------------------------------------------


@pytest.mark.parametrize("field", CONFIG_FIELDS)
def test_the_widgets_can_set_every_config_field(qtbot, window, field):
    """Perturbing one widget must move exactly that config field.

    Written as a per-field table rather than a single test so a failure names the
    field that became unreachable. It is the regression test for "the GUI can
    set everything the CLI can": add a flag, forget a spinbox, and this fails
    with the field's name on the output.
    """
    before = getattr(window.current_config(), field)
    _PERTURBATIONS[field](window)
    after = getattr(window.current_config(), field)
    assert after != before, f"the {field} widget does not reach RenderConfig.{field}"
    qtbot.addWidget(window)


def _perturb_combo(values):
    """Return a perturbation that picks the first value other than the current one."""

    def apply(window) -> None:
        combo = values(window)
        for candidate in combo.count() and range(combo.count()) or []:
            combo.setCurrentIndex(candidate)
            return

    return apply


def _set_text(window, attr, value) -> None:
    """Set a line edit, which is how every text-shaped field is edited."""
    getattr(window, attr).setText(value)


def _event_is_set(event) -> bool:
    """``waitUntil`` predicate for a threading.Event."""
    return event.is_set()


def _not_empty(items) -> bool:
    """``waitUntil`` predicate for a list a background thread appends to."""
    return bool(items)


def _deleted(obj) -> bool:
    """``waitUntil`` predicate: a QObject whose C++ half is gone."""
    return sip.isdeleted(obj)


def _button_enabled(window) -> bool:
    """``waitUntil`` predicate: the worker is done and the UI is live again.

    A named function rather than ``lambda: window.render_button.isEnabled()``
    repeated a dozen times, so that "the render finished" has one definition in
    this file and not twelve.
    """
    return bool(window.render_button.isEnabled())


_PERTURBATIONS = {
    "style": lambda w: w.style_combo.setCurrentIndex(0),
    "tiff": lambda w: _set_text(w, "tiff_edit", "/tmp/other.tif"),
    "duration": lambda w: w.duration_spin.setValue(7.0),
    "hold": lambda w: w.hold_spin.setValue(3.0),
    "fps": lambda w: w.fps_spin.setValue(11),
    "size": lambda w: w.size_combo.setCurrentIndex(2),
    "dpi": lambda w: w.dpi_spin.setValue(37),
    "margin": lambda w: w.margin_spin.setValue(1.5),
    "bounds": lambda w: _set_text(w, "bounds_edit", "1,2,3,4"),
    "logo_start": lambda w: _set_text(w, "logo_start_edit", "flag"),
    "logo_end": lambda w: _set_text(w, "logo_end_edit", "flag"),
    "logo_marker": lambda w: _set_text(w, "logo_marker_edit", "flag"),
    "logo_size_px": lambda w: w.logo_size_spin.setValue(64),
    "logo_plate_padding": lambda w: w.logo_padding_spin.setValue(0.6),
    "out": lambda w: _set_text(w, "out_edit", "/tmp/gui.mp4"),
    "output_dir": lambda w: _set_text(w, "output_dir_edit", "/tmp/gui-out"),
    "force": lambda w: w.force_check.setChecked(True),
    "appearance": lambda w: w.color_buttons["bg_color"].setText("#010203"),
    "gif": lambda w: w.gif_check.setChecked(True),
    "profile": lambda w: w.profile_combo.setCurrentIndex(0),
    "profile_width": lambda w: w.profile_width_spin.setValue(0.9),
    "profile_height": lambda w: w.profile_height_spin.setValue(0.8),
    "chart_video": lambda w: w.chart_video_check.setChecked(True),
}


def test_the_perturbation_table_covers_exactly_the_config_fields():
    """A guard on the guard: a new field with no perturbation would pass vacuously."""
    assert set(_PERTURBATIONS) == set(CONFIG_FIELDS)


def test_the_look_tab_exposes_every_appearance_field(qtbot, base):
    """The colours are a flat dict of buttons, so they need their own check."""
    appearance = dataclasses.replace(
        base.appearance, **{f: "#123456" for f, _ in STYLE_COLORS}
    )
    win = MainWindow(base=dataclasses.replace(base, appearance=appearance))
    qtbot.addWidget(win)
    for field, _ in STYLE_COLORS:
        assert win.color_buttons[field].text() == "#123456", field
    assert win.current_config().appearance.bg_color == "#123456"


def test_the_logo_and_gif_and_chart_fields_round_trip_from_a_non_default_base(
    qtbot, base
):
    """Seeding from a config file must survive the trip through the widgets.

    This is the config-layers promise: a value in ``gpx-animate.toml`` arrives in
    the GUI pre-filled, and if the user does not touch it, what renders is what
    the file said.
    """
    loaded = dataclasses.replace(
        base,
        style="none",
        tiff=Path("/tmp/a.tif"),
        out=Path("/tmp/a.mp4"),
        output_dir=Path("/tmp/a-out"),
        bounds=Bbox(-1.0, -2.0, 3.0, 4.0),
        logo_start="start",
        logo_end="end",
        logo_marker="marker",
        logo_size_px=48,
        logo_plate_padding=0.35,
        fps=24,
        dpi=150,
        margin=0.25,
        duration=6.0,
        hold=1.5,
        force=True,
        profile="bottom",
        profile_width=0.35,
        profile_height=0.45,
        chart_video=True,
        gif=dataclasses.replace(
            base.gif,
            enabled=True,
            size="480x270",
            fps=10,
            colors=128,
            dither=False,
            loop=2,
        ),
    )
    win = MainWindow(base=loaded)
    qtbot.addWidget(win)
    assert win.current_config() == loaded


@pytest.mark.usefixtures("hermetic_config")
def test_the_widgets_are_seeded_from_the_loaded_config(qtbot, tmp_path):
    """``MainWindow()`` with no base reads layers 1-4, so a TOML value shows up.

    Written as a real ``gpx-animate.toml`` rather than a monkeypatched
    ``load_config``, because the claim under test is that the GUI reads the same
    files the CLI does.
    """
    (tmp_path / "gpx-animate.toml").write_text("duration = 8.5\nfps = 12\n")
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.current_config().duration == 8.5
    assert win.current_config().fps == 12


# --- config_from_widgets ---------------------------------------------------


def test_untouched_widgets_reproduce_the_base_config_exactly():
    """The no-dirty-tracking design only works if applying every value is a no-op.

    Every widget is seeded from the base and then written back, so any field that
    comes back different is a field whose widget cannot represent what it was
    seeded with -- which is a silent capability gap, not a cosmetic one.
    """
    base = default_config()
    win = MainWindow(base=base)
    try:
        assert win.current_config() == base
    finally:
        win.deleteLater()


def test_unknown_value_names_are_ignored():
    """A widget added later must not need an edit here."""
    base = default_config()
    assert config_from_widgets(base, {"not_a_field": 1}) == base


def test_a_bad_bounds_box_raises_before_anything_renders():
    """Validation belongs in the config, so the user hears about it immediately."""
    with pytest.raises(ValueError):
        config_from_widgets(default_config(), {"bounds": _optional_bounds("1,2,3")})


def test_blank_text_means_unset_rather_than_empty_string():
    """A cleared field is 'off', not 'set to the empty string'."""
    config = config_from_widgets(
        default_config(),
        {"out": None, "tiff": None, "logo_start": None, "bounds": None},
    )
    assert config.out is None
    assert config.tiff is None
    assert config.logo_start is None
    assert config.bounds is None


def test_a_zero_logo_size_means_registry_default(qtbot, window):
    """A spinbox holds an int, not None, so zero is the sentinel and maps back.

    Asserted through the widget rather than through ``config_from_widgets``,
    because the coercion lives in the widget-reading layer -- that rule is the
    whole content of this test, and calling the pure function would skip it.
    """
    window.logo_size_spin.setValue(0)
    assert window.current_config().logo_size_px is None
    window.logo_size_spin.setValue(30)
    assert window.current_config().logo_size_px == 30


def test_path_fields_come_back_as_paths_not_strings():
    """``dataclasses.replace`` does not coerce, so the GUI has to.

    A ``str`` where the annotation promises ``Path`` still works for the first
    ``Path()`` call on it, which is why this would otherwise only show up as a
    confusing failure somewhere downstream.
    """
    config = config_from_widgets(
        default_config(),
        {
            "out": Path("/tmp/x.mp4"),
            "output_dir": Path("/tmp/x"),
            "tiff": Path("/tmp/x.tif"),
        },
    )
    assert isinstance(config.out, Path)
    assert isinstance(config.output_dir, Path)
    assert isinstance(config.tiff, Path)


def test_nested_dataclasses_are_replaced_whole():
    """``appearance`` and ``gif`` are replaced, not merged field by field."""
    base = default_config()
    config = config_from_widgets(base, {"appearance": {"bg_color": "#010203"}})
    assert config.appearance.bg_color == "#010203"
    assert config.appearance.font == base.appearance.font


def test_the_gui_does_not_clamp_a_mismatched_gif_fps():
    """Neither front end clamps, so the GUI must not start clamping either.

    A clamp here would be a silent divergence from the CLI, and it would also
    hide a real user mistake: a GIF "faster" than the frames it is sampled from
    is not achievable by sampling. The encoder rejects the pair with a clear
    message instead, which the failure path above already covers.
    """
    config = config_from_widgets(default_config(), {"fps": 10, "gif": {"fps": 30}})
    assert config.fps == 10
    assert config.gif.fps == 30


def test_style_default_is_not_hardcoded_in_the_widgets():
    """The combo is built from ``style_choices()``, so it follows the machine.

    A hardcoded list would offer Carto styles without an API key and hide
    ``none`` on a machine that has tiles -- the CLI would then and the GUI would
    not, which is the exact asymmetry this project is trying to avoid.
    """

    win = MainWindow(base=default_config())
    try:
        offered = [win.style_combo.itemText(i) for i in range(win.style_combo.count())]
        assert offered == list(style_choices())
    finally:
        win.deleteLater()


def test_the_profile_combo_offers_every_position():
    """``PROFILE_POSITIONS`` is the source of truth; the combo must not narrow it."""
    win = MainWindow(base=default_config())
    try:
        offered = [
            win.profile_combo.itemText(i) for i in range(win.profile_combo.count())
        ]
        assert set(offered) == set(PROFILE_POSITIONS)
    finally:
        win.deleteLater()


def test_the_size_combo_offers_every_preset():

    win = MainWindow(base=default_config())
    try:
        offered = [win.size_combo.itemText(i) for i in range(win.size_combo.count())]
        assert set(offered) == set(SIZES)
    finally:
        win.deleteLater()


# --- window behaviour ------------------------------------------------------


def test_the_nine_tabs_are_all_there(qtbot, window):
    """A tab that goes missing hides fields with no test failing."""
    tabs = window.findChild(QTabWidget)
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert labels == [
        "Source",
        "Map",
        "Timing",
        "Look",
        "Logos",
        "Output",
        "GIF",
        "Chart",
        "Log",
    ]


def test_pressing_render_with_no_file_reports_an_error_and_renders_nothing(
    qtbot, window
):
    """An empty line edit is a user error, not a crash."""
    window.start_render()
    assert "GPX" in window.status_label.text()
    assert "ERROR" in window.log_view.toPlainText()
    assert window.render_button.isEnabled()


def test_a_bad_config_reports_an_error_without_starting_a_thread(
    qtbot, window, tmp_path
):
    """Fail fast: the message must arrive before a render, not after 150 frames."""
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    _set_text(window, "bounds_edit", "not,a,box")
    window.start_render()
    assert "ERROR" in window.log_view.toPlainText()
    assert window._worker is None


def test_a_render_disables_the_button_and_reenables_it(
    qtbot, window, monkeypatch, tmp_path
):
    """One render at a time, and the controls come back afterwards."""
    calls: list[RenderConfig] = []

    def fake_render(config, gpx, *, logo_registry=None):
        calls.append(config)
        return tmp_path / "out.mp4"

    monkeypatch.setattr(gui_main, "render_to_video", fake_render)
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))

    window.start_render()
    assert window.render_button.isEnabled() is False
    assert window.progress.isHidden() is False

    qtbot.waitUntil(partial(_button_enabled, window))
    assert calls, "the worker never called the pipeline"
    assert calls[0].duration == window.duration_spin.value()
    assert window.progress.isHidden() is True
    assert "out.mp4" in window.status_label.text()


def test_the_registry_is_passed_to_the_pipeline_as_a_path(
    qtbot, window, monkeypatch, tmp_path
):
    """``logo_registry`` is front-end wiring, not a config field, so it is plumbed."""
    seen: list[object] = []
    monkeypatch.setattr(
        gui_main,
        "render_to_video",
        lambda config, gpx, *, logo_registry=None: seen.append(logo_registry),
    )
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    _set_text(window, "registry_edit", str(tmp_path / "logos.yaml"))
    window.start_render()
    qtbot.waitUntil(partial(_button_enabled, window))
    assert seen == [tmp_path / "logos.yaml"]


def test_a_blank_registry_means_none(qtbot, window, monkeypatch, tmp_path):
    """Blank is 'no registry', and None is what the pipeline expects."""
    seen: list[object] = []
    monkeypatch.setattr(
        gui_main,
        "render_to_video",
        lambda config, gpx, *, logo_registry=None: seen.append(logo_registry),
    )
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    window.start_render()
    qtbot.waitUntil(partial(_button_enabled, window))
    assert seen == [None]


def test_pressing_render_twice_does_not_start_two_renders(
    qtbot, window, monkeypatch, tmp_path
):
    """A second click mid-render must be ignored, not queued."""
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow_render(config, gpx, *, logo_registry=None):
        calls.append(1)
        started.set()
        release.wait(5)
        return tmp_path / "out.mp4"

    monkeypatch.setattr(gui_main, "render_to_video", slow_render)
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    window.start_render()
    qtbot.waitUntil(partial(_event_is_set, started))
    window.start_render()
    release.set()
    qtbot.waitUntil(partial(_button_enabled, window))
    assert len(calls) == 1, "a second render was started while one was running"


def test_a_failed_render_reports_the_message_and_leaves_the_window_usable(
    qtbot, window, monkeypatch, tmp_path
):
    """A render that fails is a log line, not a dead window."""

    def boom(config, gpx, *, logo_registry=None):
        raise NoPointsError("no points in that file")

    monkeypatch.setattr(gui_main, "render_to_video", boom)
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    window.start_render()
    qtbot.waitUntil(partial(_button_enabled, window))
    assert "no points" in window.status_label.text()
    assert window.render_button.isEnabled()


def test_library_log_records_reach_the_log_pane(qtbot, window):
    """The library logs; the GUI shows it, rather than printing to nowhere."""
    logging.getLogger("gpx_animate.probe").info("a line from the render")
    qtbot.waitUntil(lambda: "a line from the render" in window.log_view.toPlainText())


def test_the_log_pane_captures_records_from_another_thread(qtbot, window):
    """The render thread's logging must not touch widgets directly.

    This is the whole reason the bridge is a signal. Without the queued
    connection this is a crash or a silent no-op depending on timing, so the
    test asserts the line arrives rather than that nothing exploded.
    """

    def emit() -> None:
        logging.getLogger("gpx_animate.worker").info("from the worker thread")

    thread = threading.Thread(target=emit)
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: "from the worker thread" in window.log_view.toPlainText())


def test_the_log_level_dropdown_moves_the_root_logger(qtbot, window):
    """Changing the level has to reach the library, not just the pane."""
    window.level_combo.setCurrentText("ERROR")
    assert logging.getLogger().level == logging.ERROR
    window.level_combo.setCurrentText("INFO")
    assert logging.getLogger().level == logging.INFO


def test_an_unknown_log_level_falls_back_to_info(qtbot, window):
    """The combo is a closed list, but the handler should not raise on a typo."""
    window._set_log_level("NOPE")
    assert logging.getLogger().level == logging.INFO


def test_closing_while_a_render_runs_asks_first(qtbot, window, monkeypatch, tmp_path):
    """Killing a render on close would leave a half-written file and no message."""

    started = threading.Event()
    release = threading.Event()

    def slow_render(config, gpx, *, logo_registry=None):
        started.set()
        release.wait(5)
        return tmp_path / "out.mp4"

    monkeypatch.setattr(gui_main, "render_to_video", slow_render)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    _set_text(window, "gpx_edit", str(tmp_path / "t.gpx"))
    window.start_render()
    assert started.wait(5)

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is False

    release.set()
    qtbot.waitUntil(partial(_button_enabled, window))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    event2 = QCloseEvent()
    window.closeEvent(event2)
    assert event2.isAccepted() is True


def test_closing_an_idle_window_just_closes(qtbot, window):
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is True


def test_picking_a_colour_updates_the_swatch(qtbot, window, monkeypatch):
    """The swatch's text is the value, which is why this is worth pinning."""

    def chosen(*_args, **_kwargs):
        return QColor("#ff8800")

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(chosen))
    window._pick_color("track_bright")
    assert window.color_buttons["track_bright"].text() == "#ff8800"
    assert window.current_config().appearance.track_bright == "#ff8800"


def test_cancelling_the_colour_dialog_leaves_the_value_alone(
    qtbot, window, monkeypatch
):

    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        staticmethod(lambda *a, **k: QColor()),  # invalid
    )
    before = window.current_config().appearance.track_bright
    window._pick_color("track_bright")
    assert window.current_config().appearance.track_bright == before


def test_the_browse_buttons_write_into_their_fields(
    qtbot, window, monkeypatch, tmp_path
):
    """The file dialogs are thin, but a mis-wired one silently does nothing."""

    chosen = tmp_path / "trip.gpx"
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    window._pick_gpx()
    assert window.current_gpx() == chosen

    tiff = tmp_path / "map.tif"
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(tiff), ""))
    )
    window._pick_into(window.tiff_edit, "GeoTIFF")
    assert window.current_config().tiff == tiff


def test_cancelling_a_file_dialog_changes_nothing(qtbot, window, monkeypatch):

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    window._pick_gpx()
    assert window.gpx_edit.text() == ""


def test_current_gpx_rejects_a_blank_field(window):
    with pytest.raises(ValueError, match="GPX"):
        window.current_gpx()


# --- the worker ------------------------------------------------------------


def test_the_worker_runs_off_the_gui_thread(qtbot, monkeypatch, tmp_path):
    """A render on the GUI thread freezes the window; this pins that it is not.

    The assertion is the thread *identity*, not the timing: ``get_ident`` on the
    worker versus the one pytest-qt runs the test on.
    """

    seen: list[int] = []

    def record_the_thread(config, gpx, *, logo_registry=None):
        seen.append(threading.get_ident())
        return tmp_path / "v.mp4"

    monkeypatch.setattr(gui_main, "render_to_video", record_the_thread)
    worker = RenderWorker(default_config(), tmp_path / "t.gpx")
    worker.start()
    # waitUntil raises TimeoutError if the predicate never comes true; it returns
    # None either way, so asserting on its return value would always fail.
    qtbot.waitUntil(partial(_not_empty, seen), timeout=5000)
    worker.wait(5000)
    assert seen == [seen[0]]
    assert seen[0] != threading.get_ident()


def test_the_worker_reports_the_output_path(qtbot, monkeypatch, tmp_path):

    monkeypatch.setattr(
        gui_main,
        "render_to_video",
        lambda config, gpx, *, logo_registry=None: tmp_path / "v.mp4",
    )
    worker = RenderWorker(default_config(), tmp_path / "t.gpx")
    with qtbot.waitSignal(worker.succeeded) as blocker:
        worker.run()
    assert str(tmp_path / "v.mp4") in [str(a) for a in blocker.args]


def test_the_worker_turns_a_deliberate_failure_into_a_message(
    qtbot, monkeypatch, tmp_path
):
    """No traceback, and the window survives -- the same contract as the CLI."""

    def boom(config, gpx, *, logo_registry=None):
        raise OSError("ffmpeg is not on PATH")

    monkeypatch.setattr(gui_main, "render_to_video", boom)
    worker = RenderWorker(default_config(), tmp_path / "t.gpx")
    with qtbot.waitSignal(worker.failed) as blocker:
        worker.run()
    assert "ffmpeg" in str(blocker.args)


def test_the_worker_reports_a_bad_config_value(qtbot, monkeypatch, tmp_path):
    """A ValueError from the domain is a user error, so it is caught too."""

    def boom(config, gpx, *, logo_registry=None):
        raise ValueError("bounds are inverted")

    monkeypatch.setattr(gui_main, "render_to_video", boom)
    worker = RenderWorker(default_config(), tmp_path / "t.gpx")
    with qtbot.waitSignal(worker.failed) as blocker:
        worker.run()
    assert "inverted" in str(blocker.args)


def test_the_worker_lets_an_unexpected_error_kill_the_thread(
    qtbot, monkeypatch, tmp_path
):
    """A bug must not be swallowed into a log line pretending to be understood.

    Only the three documented exception types are caught; anything else is a
    crash, which is the honest signal.
    """

    def boom(config, gpx, *, logo_registry=None):
        raise RuntimeError("a genuine bug")

    monkeypatch.setattr(gui_main, "render_to_video", boom)
    worker = RenderWorker(default_config(), tmp_path / "t.gpx")
    with pytest.raises(RuntimeError, match="genuine bug"):
        worker.run()


def test_the_log_handler_survives_a_record_it_cannot_format(qtbot):
    """A logging failure must not take the render down with it.

    ``emit`` runs inside whatever code logged, so letting an exception escape
    would turn a cosmetic problem into a failed render.
    """

    class Unprintable:
        def __str__(self):
            raise RuntimeError("nope")

    bridge = _LogBridge()
    handler = _PaneEmitter(bridge)
    record = logging.LogRecord("x", logging.INFO, "f", 1, Unprintable(), None, None)
    handler.emit(record)  # must not raise


def test_the_log_handler_ignores_a_deleted_bridge(qtbot):
    """A handler must outlive its window without crashing the process.

    The handler sits on the *root* logger, which is process-wide and long-lived,
    while the bridge belongs to a window that can be closed at any moment.
    Emitting into a collected QObject is freed memory, so the handler checks
    first and drops the record.
    """
    bridge = _LogBridge()
    handler = _PaneEmitter(bridge)
    bridge.deleteLater()
    qtbot.waitUntil(partial(_deleted, bridge))
    record = logging.LogRecord("x", logging.INFO, "f", 1, "after the close", None, None)
    handler.emit(record)  # must not raise


def test_a_closed_window_takes_its_log_handler_off_the_root_logger(qtbot, window):
    """Otherwise every window ever opened leaves a handler behind forever."""
    before = len(logging.getLogger().handlers)
    window.closeEvent(QCloseEvent())
    assert len(logging.getLogger().handlers) == before - 1


@pytest.mark.usefixtures("hermetic_config")
def test_the_gui_still_starts_when_qt_is_present(qtbot, monkeypatch):
    """``main`` wires up a QApplication and shows a window.

    ``exec`` is stubbed so the test does not block; everything before it is the
    part worth testing.
    """

    shown: list[bool] = []
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(MainWindow, "show", lambda self: shown.append(True))
    assert gui_entry_point([]) == 0
    assert shown == [True]


def test_main_tolerates_the_argv_a_console_script_passes():
    """The entry point gets sys.argv; argv is accepted and ignored either way."""

    signature = inspect.signature(gui_entry_point)
    assert list(signature.parameters) == ["argv"]


def test_the_module_exposes_the_entry_point_pyproject_declares():
    """A rename that breaks ``gpx-animate-gui`` must fail a test, not a user."""
    assert callable(gui_entry_point)


def test_the_gui_module_is_importable_without_a_display(qtbot):
    """Constructing the window is enough; showing it is not needed."""
    win = MainWindow(base=default_config())
    qtbot.addWidget(win)
    assert win.windowTitle() == "gpx-animate"


def test_the_environment_variable_the_offscreen_platform_needs_is_set_by_the_suite():
    """Documented in conftest; asserted so removing it does not silently pass."""
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"


def test_the_appearance_dataclass_is_untouched_by_the_gui():
    """Sanity: the widget bridge does not mutate the shared frozen-ish default."""
    style = Style()
    before = dataclasses.asdict(style)
    win = MainWindow(base=default_config())
    try:
        win.current_config()
    finally:
        win.deleteLater()
    assert dataclasses.asdict(style) == before


def test_gui_package_exposes_main():
    """``gpx_animate.adapters.gui`` is a package, not a bare module."""
    assert hasattr(gui_package, "main")


# --- finding the finished video ---------------------------------------------
#
# A non-technical user is not reading the log pane for a path. These tests pin
# the affordance that turns "a plausible-looking window that worked" into "a
# file I can see", which is the difference between a program and a puzzle.


class TestOpenOutputFolder:
    def test_the_button_starts_disabled(self, window):
        """Before any render there is no output to open.

        Enabled-but-useless would open a directory that does not exist yet,
        which reads as a broken button rather than an unhelpful one.
        """
        assert window.open_output_button.isEnabled() is False

    def test_a_finished_render_enables_it(self, window, tmp_path):
        window._report_success(str(tmp_path / "output" / "trip.mp4"))
        assert window.open_output_button.isEnabled() is True

    def test_it_opens_the_folder_holding_the_video(self, window, tmp_path, monkeypatch):
        """The folder, not the file: Explorer opening the mp4 is not helpful."""
        opened = []
        monkeypatch.setattr(
            gui_main.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
        )
        out = tmp_path / "output" / "trip.mp4"
        window._report_success(str(out))

        window.open_output_button.click()

        assert len(opened) == 1
        assert opened[0].toLocalFile() == str(out.parent)

    def test_clicking_it_before_a_render_does_nothing(self, window, monkeypatch):
        opened = []
        monkeypatch.setattr(
            gui_main.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
        )
        window._open_output_folder()
        assert opened == []

    def test_it_uses_qt_rather_than_a_shell(self, window, tmp_path, monkeypatch):
        """QDesktopServices follows whatever the desktop registered, and a
        configured path cannot turn it into a way to run something else."""
        calls = []
        monkeypatch.setattr(
            gui_main.QDesktopServices, "openUrl", lambda url: calls.append(url) or True
        )
        window._report_success(str(tmp_path / "o" / "v.mp4"))
        window._open_output_folder()
        assert len(calls) == 1

    def test_a_refused_open_is_reported_but_not_fatal(
        self, window, tmp_path, monkeypatch
    ):
        """No desktop handler registered must not crash a finished render, and
        must not read as "the video is gone"."""
        monkeypatch.setattr(gui_main.QDesktopServices, "openUrl", lambda url: False)
        window._report_success(str(tmp_path / "o" / "v.mp4"))

        window._open_output_folder()

        assert "could not open" in window.log_view.toPlainText()

    def test_a_second_render_repoints_the_button(self, window, tmp_path, monkeypatch):
        """Otherwise it would open the first run's folder, which by then holds
        an older video and no sign of the one just finished."""
        opened = []
        monkeypatch.setattr(
            gui_main.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
        )
        window._report_success(str(tmp_path / "first" / "a.mp4"))
        window._report_success(str(tmp_path / "second" / "b.mp4"))

        window._open_output_folder()

        assert opened[0].toLocalFile() == str(tmp_path / "second")
