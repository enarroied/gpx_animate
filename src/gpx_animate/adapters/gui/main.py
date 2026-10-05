"""The PyQt adapter: a second front end over the same application layer.

This module does not replace the CLI and is not a wrapper around it. Both front
ends call :func:`gpx_animate.adapters.pipeline.render_to_video` — the same
function object, which a test asserts by identity — and differ only in how a
user's choices arrive: ``argparse`` there, widgets here. Everything below the
widgets, from the config dataclasses through the use cases to the adapters, is
shared. That is the whole point of the hexagonal split, and this adapter is the
proof of it.

Two consequences worth stating, because both are easy to get wrong:

* **No logic lives here.** This file turns widget values into a
  :class:`RenderConfig` and then calls the pipeline. It does not decide where
  output goes, check whether a GIF is possible, or sequence the renders — the
  pipeline owns all of that, because a GUI that reimplemented it would be a
  second wiring that drifts from the first.
* **It never shells out.** A ``QProcess`` running ``gpx-animate`` would be far
  less code, and would quietly turn the GUI into a front end *for* the CLI
  rather than a peer of it. The render runs in-process on a worker thread.

Widgets are seeded from the loaded config (layers 1-4 of SPECS section 5: the
shipped defaults, the user TOML, the project TOML and the environment), so a
value set in ``gpx-animate.toml`` arrives pre-filled in the GUI and behaves the
same way it does on the command line. Because the widgets start at the base
values and :func:`config_from_widgets` applies all of them, an untouched widget
overwrites a field with the value it was seeded from -- which is a no-op. That
is why there is no dirty-tracking here.

Requires the ``gui`` extra::

    uv sync --extra gui
    uv run gpx-animate-gui
"""

from __future__ import annotations

import dataclasses
import logging
import sys
from pathlib import Path
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtCore import QThread
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QColorDialog
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QDoubleSpinBox
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtWidgets import QFormLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtWidgets import QProgressBar
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QSpinBox
from PyQt6.QtWidgets import QTabWidget
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from gpx_animate.adapters.basemaps.factory import style_choices
from gpx_animate.adapters.pipeline import render_to_video
from gpx_animate.application.errors import GpxAnimateError
from gpx_animate.config.defaults import SIZES
from gpx_animate.config.loader import load_config
from gpx_animate.domain.bbox import parse_bounds
from gpx_animate.domain.render_config import PROFILE_POSITIONS
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import Style


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
"""Levels for the log pane's dropdown, matching the CLI's ``--log-level``."""

STYLE_COLORS = (
    ("bg_color", "Background"),
    ("track_faint", "Track (faint)"),
    ("track_bright", "Track (drawn)"),
    ("marker_color", "Marker"),
    ("hud_color", "HUD text"),
    ("title_color", "Title"),
)
"""Which :class:`Style` fields get a colour swatch, and their labels."""


def config_from_widgets(base: RenderConfig, values: dict[str, Any]) -> RenderConfig:
    """Build a config from a base one and the values the widgets currently hold.

    Every value is applied, not just the changed ones. The widgets are seeded
    from ``base`` when the window opens, so applying an untouched field writes
    back what it was seeded with. Dirty-tracking would add a second source of
    truth for "what did the user change" and would drift the moment a field is
    added.

    ``appearance`` and ``gif`` are nested dataclasses, so they are replaced
    whole rather than merged field by field.

    Args:
        base: The config from layers 1-4. Never mutated.
        values: Field names to values, as read off the widgets. Unknown names
            are ignored so a widget can be added without touching this
            function.

    Returns:
        A new validated config. Validation happens in
        :meth:`RenderConfig.__post_init__`, so a bad value raises here rather
        than halfway through a render.
    """
    updates = {name: value for name, value in values.items() if name in _CONFIG_FIELDS}
    if "appearance" in values:
        updates["appearance"] = dataclasses.replace(
            base.appearance, **values["appearance"]
        )
    if "gif" in values:
        updates["gif"] = dataclasses.replace(base.gif, **values["gif"])
    return dataclasses.replace(base, **updates)


def _text(value: str) -> str | None:
    """Empty text means 'not set', not 'the empty string'."""
    return value.strip() or None


def _optional_path(text: str) -> Path | None:
    """Blank means 'not set', and a set path is a real ``Path``.

    ``dataclasses.replace`` does not coerce, so handing it the line edit's
    ``str`` would build a config whose ``tiff``/``out`` were strings where the
    field promises a ``Path``. A later ``Path`` operation would still work, which
    is exactly why this would not have been caught by a smoke render.
    """
    return Path(text.strip()) if text.strip() else None


def _optional_int(value: int) -> int | None:
    """A zero spinbox means 'leave it to the logo', matching ``--logo-size``."""
    return value or None


def _optional_bounds(text: str) -> Any:
    """Parse the bounds field, treating blank as unset.

    Returns:
        A :class:`~gpx_animate.domain.bbox.Bbox`, or ``None`` when the field is
        blank.

    Raises:
        ValueError: The text is not four comma-separated degrees. Raised while
            the config is being built, which is before any rendering starts.
    """
    return parse_bounds(text) if text.strip() else None


_CONFIG_FIELDS = frozenset(f.name for f in dataclasses.fields(RenderConfig))
"""Derived, so a new domain field is settable from the GUI with no edit here."""


class _PaneEmitter(logging.Handler):
    """Ship library log records into a Qt signal.

    A handler rather than a print, because the library logs through
    :mod:`logging` and the CLI configures that to stdout. A GUI has no stdout to
    read, so it attaches its own handler and leaves the root logger's level
    alone.

    Emitting a signal is safe from the render thread: Qt delivers it to the GUI
    thread through a queued connection, which is what keeps a log line from
    touching a widget from the wrong thread.

    The handler holds the bridge object rather than its bound signal, and checks
    that the bridge is still alive before emitting. Holding a bound signal means
    holding a reference to a C++ object that Python is free to collect; the
    handler then outlives it and the next log line dereferences freed memory,
    which takes the process down with no traceback. That is not hypothetical --
    it is what a window that is closed while records are still arriving looks
    like.
    """

    def __init__(self, bridge: _LogBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a record's message, ignoring anything unformattable."""
        try:
            if sip.isdeleted(self._bridge):
                return
            signal_instance = self._bridge.message
            signal_instance.emit(record.getMessage())
        except Exception:  # noqa: BLE001
            self.handleError(record)


class RenderWorker(QThread):
    """Runs one render off the GUI thread.

    A render is seconds of tile downloads and matplotlib drawing. Doing it on
    the GUI thread would freeze the window, so it runs here and reports back
    through signals.
    """

    succeeded = pyqtSignal(str)
    """The path the video was written to."""

    failed = pyqtSignal(str)
    """A message for the log pane, never a traceback."""

    def __init__(
        self,
        config: RenderConfig,
        gpx: Path,
        logo_registry: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._gpx = gpx
        self._logo_registry = logo_registry

    def run(self) -> None:
        """Render, reporting the outcome as a signal.

        The exception set is the CLI's: a deliberate failure gets a message
        rather than a traceback, and the window survives it.
        """
        try:
            out_path = render_to_video(
                self._config, self._gpx, logo_registry=self._logo_registry
            )
        except (GpxAnimateError, OSError, ValueError) as error:
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(str(out_path))


class MainWindow(QMainWindow):
    """The window: every :class:`RenderConfig` field, and a Render button.

    Args:
        base: The config from layers 1-4 to seed the widgets with. Defaults to
            reading them from the working directory, which is what the CLI does
            too. Tests pass an explicit config so results do not depend on the
            developer's own ``gpx-animate.toml`` or environment.
    """

    def __init__(
        self, base: RenderConfig | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._base = load_config(Path.cwd()) if base is None else base
        self._worker: RenderWorker | None = None

        self.setWindowTitle("gpx-animate")
        self.resize(720, 560)

        tabs = QTabWidget()
        tabs.addTab(self._source_tab(), "Source")
        tabs.addTab(self._map_tab(), "Map")
        tabs.addTab(self._timing_tab(), "Timing")
        tabs.addTab(self._look_tab(), "Look")
        tabs.addTab(self._logo_tab(), "Logos")
        tabs.addTab(self._output_tab(), "Output")
        tabs.addTab(self._gif_tab(), "GIF")
        tabs.addTab(self._chart_tab(), "Chart")
        tabs.addTab(self._log_tab(), "Log")

        outer = QVBoxLayout()
        outer.addWidget(tabs)
        shell = QWidget()
        shell.setLayout(outer)
        self.setCentralWidget(shell)

        self.log_lines = _LogBridge()
        self.log_lines.message.connect(self._append_log)
        self._attach_logging()

    def _attach_logging(self) -> None:
        """Route the library's log records into this window's log pane.

        A handler is attached rather than logging reconfigured globally, so
        importing this module does not silently change how anything else in the
        process logs. A window constructed twice attaches twice, which is why
        tests get a fresh logger state from the fixture.
        """
        self._log_handler = _PaneEmitter(self.log_lines)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(self._log_handler)

    def _detach_logging(self) -> None:
        """Take this window's handler off the root logger.

        Called when the window closes. Without it every window ever opened
        leaves a handler behind, and the last one standing keeps a bridge alive
        that nobody can see any more.
        """
        handler = getattr(self, "_log_handler", None)
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            self._log_handler = None

    # -- tabs ---------------------------------------------------------------

    def _source_tab(self) -> QWidget:
        self.gpx_edit = QLineEdit()
        self.gpx_edit.setPlaceholderText("trip.gpx")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_gpx)
        row = QHBoxLayout()
        row.addWidget(self.gpx_edit)
        row.addWidget(browse)

        body = QVBoxLayout()
        body.addLayout(self._form("GPX file", row))
        body.addWidget(
            QLabel(
                "The GUI and the CLI read the same config files and environment "
                "variables, so anything set outside this window shows up here."
            )
        )
        body.addStretch()
        return self._tab(body)

    def _map_tab(self) -> QWidget:
        self.style_combo = QComboBox()
        self.style_combo.addItems(style_choices())
        self.style_combo.setCurrentText(self._base.style)

        self.tiff_edit = QLineEdit(_as_text(self._base.tiff))
        self.tiff_edit.setPlaceholderText("optional GeoTIFF, overrides --style")
        tiff_browse = QPushButton("Browse...")
        tiff_browse.clicked.connect(
            lambda: self._pick_into(self.tiff_edit, "GeoTIFF (*.tif *.tiff)")
        )
        tiff_row = QHBoxLayout()
        tiff_row.addWidget(self.tiff_edit)
        tiff_row.addWidget(tiff_browse)

        self.size_combo = QComboBox()
        self.size_combo.addItems(sorted(SIZES))
        self.size_combo.setCurrentText(self._base.size)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(1, 1200)
        self.dpi_spin.setValue(self._base.dpi)

        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.0, 5.0)
        self.margin_spin.setSingleStep(0.05)
        self.margin_spin.setValue(self._base.margin)

        self.bounds_edit = QLineEdit(
            ""
            if self._base.bounds is None
            else ",".join(str(v) for v in self._base.bounds)
        )
        self.bounds_edit.setPlaceholderText("min_lon,min_lat,max_lon,max_lat")

        body = QVBoxLayout()
        for label, widget in (
            ("Style", self.style_combo),
            ("GeoTIFF", tiff_row),
            ("Size", self.size_combo),
            ("DPI", self.dpi_spin),
            ("Margin", self.margin_spin),
            ("Fixed bounds", self.bounds_edit),
        ):
            body.addLayout(self._form(label, widget))
        body.addStretch()
        return self._tab(body)

    def _timing_tab(self) -> QWidget:
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 600.0)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setValue(self._base.duration)

        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(0.0, 600.0)
        self.hold_spin.setSuffix(" s")
        self.hold_spin.setValue(self._base.hold)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(self._base.fps)

        body = QVBoxLayout()
        for label, widget in (
            ("Duration", self.duration_spin),
            ("Hold", self.hold_spin),
            ("Frame rate", self.fps_spin),
        ):
            body.addLayout(self._form(label, widget))
        body.addWidget(
            QLabel("Frames = duration x fps + hold x fps, truncated to whole frames.")
        )
        body.addStretch()
        return self._tab(body)

    def _look_tab(self) -> QWidget:
        self.color_buttons: dict[str, QPushButton] = {}
        body = QVBoxLayout()
        for field, label in STYLE_COLORS:
            button = QPushButton()
            button.setText(getattr(self._base.appearance, field))
            button.setStyleSheet(
                f"background-color: {getattr(self._base.appearance, field)}"
            )
            button.clicked.connect(lambda _checked=False, f=field: self._pick_color(f))
            self.color_buttons[field] = button
            body.addLayout(self._form(label, button))

        self.font_edit = QLineEdit(self._base.appearance.font)
        body.addLayout(self._form("Font", self.font_edit))
        body.addStretch()
        return self._tab(body)

    def _logo_tab(self) -> QWidget:
        self.logo_start_edit = QLineEdit(_as_text(self._base.logo_start))
        self.logo_end_edit = QLineEdit(_as_text(self._base.logo_end))
        self.logo_marker_edit = QLineEdit(_as_text(self._base.logo_marker))

        self.logo_size_spin = QSpinBox()
        self.logo_size_spin.setRange(0, 4000)
        self.logo_size_spin.setSpecialValueText("registry default")
        self.logo_size_spin.setValue(self._base.logo_size_px or 0)

        self.logo_padding_spin = QDoubleSpinBox()
        self.logo_padding_spin.setRange(0.0, 1.0)
        self.logo_padding_spin.setSingleStep(0.02)
        self.logo_padding_spin.setValue(self._base.logo_plate_padding)

        self.registry_edit = QLineEdit()
        self.registry_edit.setPlaceholderText("logos/registry.yaml")

        rows = []
        for label, edit in (
            ("Start", self.logo_start_edit),
            ("End", self.logo_end_edit),
            ("Moving marker", self.logo_marker_edit),
        ):
            browse = QPushButton("Browse...")
            browse.clicked.connect(
                lambda _c=False, e=edit: self._pick_into(e, "Images (*.png)")
            )
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(browse)
            rows.append((label, row))

        reg_browse = QPushButton("Browse...")
        reg_browse.clicked.connect(
            lambda: self._pick_into(self.registry_edit, "YAML (*.yaml *.yml)")
        )
        reg_row = QHBoxLayout()
        reg_row.addWidget(self.registry_edit)
        reg_row.addWidget(reg_browse)
        rows.append(("Registry", reg_row))

        body = QVBoxLayout()
        for label, widget in rows:
            body.addLayout(self._form(label, widget))
        for label, widget in (
            ("Size px", self.logo_size_spin),
            ("Plate padding", self.logo_padding_spin),
        ):
            body.addLayout(self._form(label, widget))
        body.addWidget(
            QLabel(
                "A source is a file path or a name from the registry. Plate padding 0 draws no plate."
            )
        )
        body.addStretch()
        return self._tab(body)

    def _output_tab(self) -> QWidget:
        self.out_edit = QLineEdit(_as_text(self._base.out))
        self.out_edit.setPlaceholderText(
            "leave blank for a timestamped name in the output dir"
        )
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(
            lambda: self._pick_into(self.out_edit, "Video (*.mp4)")
        )
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit)
        out_row.addWidget(out_browse)

        self.output_dir_edit = QLineEdit(str(self._base.output_dir))
        self.force_check = QCheckBox("Overwrite instead of numbering")
        self.force_check.setChecked(self._base.force)

        body = QVBoxLayout()
        body.addLayout(self._form("Output file", out_row))
        body.addLayout(self._form("Output directory", self.output_dir_edit))
        body.addWidget(self.force_check)
        body.addStretch()
        return self._tab(body)

    def _gif_tab(self) -> QWidget:
        gif = self._base.gif
        self.gif_check = QCheckBox("Also write a GIF")
        self.gif_check.setChecked(gif.enabled)
        self.gif_size_edit = QLineEdit(gif.size)
        self.gif_fps_spin = QSpinBox()
        self.gif_fps_spin.setRange(1, 120)
        self.gif_fps_spin.setValue(gif.fps)
        self.gif_colors_combo = QComboBox()
        self.gif_colors_combo.addItems(["64", "128", "256"])
        self.gif_colors_combo.setCurrentText(str(gif.colors))
        self.gif_dither_check = QCheckBox("Dither (smaller without it)")
        self.gif_dither_check.setChecked(gif.dither)
        self.gif_loop_spin = QSpinBox()
        self.gif_loop_spin.setRange(0, 1000)
        self.gif_loop_spin.setSpecialValueText("forever")
        self.gif_loop_spin.setValue(gif.loop)

        body = QVBoxLayout()
        body.addWidget(self.gif_check)
        for label, widget in (
            ("GIF size", self.gif_size_edit),
            ("GIF frame rate", self.gif_fps_spin),
            ("Palette colours", self.gif_colors_combo),
            ("Loop", self.gif_loop_spin),
        ):
            body.addLayout(self._form(label, widget))
        body.addWidget(self.gif_dither_check)
        body.addWidget(
            QLabel(
                "The GIF reuses the video's frames, so its frame rate cannot exceed the video's."
            )
        )
        body.addStretch()
        return self._tab(body)

    def _chart_tab(self) -> QWidget:
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(sorted(PROFILE_POSITIONS))
        self.profile_combo.setCurrentText(self._base.profile)

        self.profile_width_spin = QDoubleSpinBox()
        self.profile_width_spin.setRange(0.05, 1.0)
        self.profile_width_spin.setSingleStep(0.01)
        self.profile_width_spin.setValue(self._base.profile_width)

        self.profile_height_spin = QDoubleSpinBox()
        self.profile_height_spin.setRange(0.05, 1.0)
        self.profile_height_spin.setSingleStep(0.01)
        self.profile_height_spin.setValue(self._base.profile_height)

        self.chart_video_check = QCheckBox("Also write the chart as its own video")
        self.chart_video_check.setChecked(self._base.chart_video)

        body = QVBoxLayout()
        for label, widget in (
            ("Chart position", self.profile_combo),
            ("Chart width", self.profile_width_spin),
            ("Chart height", self.profile_height_spin),
        ):
            body.addLayout(self._form(label, widget))
        body.addWidget(self.chart_video_check)
        body.addWidget(
            QLabel("top and bottom span the full width and ignore the width above.")
        )
        body.addStretch()
        return self._tab(body)

    def _log_tab(self) -> QWidget:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        self.level_combo = QComboBox()
        self.level_combo.addItems(LOG_LEVELS)
        self.level_combo.setCurrentText("INFO")
        self.level_combo.currentTextChanged.connect(self._set_log_level)

        self.render_button = QPushButton("Render")
        self.render_button.clicked.connect(self.start_render)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)

        self.status_label = QLabel("Choose a GPX file, then press Render.")

        body = QVBoxLayout()
        body.addWidget(self.log_view)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Log level"))
        controls.addWidget(self.level_combo)
        controls.addStretch()
        controls.addWidget(self.progress)
        controls.addWidget(self.render_button)
        body.addLayout(controls)
        body.addWidget(self.status_label)
        return self._tab(body)

    # -- behaviour ----------------------------------------------------------

    def current_config(self) -> RenderConfig:
        """The config the widgets currently describe.

        Raises:
            ValueError: A field is invalid — a malformed bounds box, a negative
                logo size. Raised while building the config, so the message
                reaches the user before any rendering starts.
        """
        return config_from_widgets(self._base, self._widget_values())

    def current_gpx(self) -> Path:
        """The chosen track file.

        Raises:
            ValueError: No file chosen.
        """
        text = self.gpx_edit.text().strip()
        if not text:
            raise ValueError("Choose a GPX file first.")
        return Path(text)

    def start_render(self) -> None:
        """Validate the widgets, then render on a worker thread."""
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            config = self.current_config()
            gpx = self.current_gpx()
        except (ValueError, OSError) as error:
            self._report_failure(str(error))
            return

        registry = _text(self.registry_edit.text())
        self.render_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Rendering...")

        self._worker = RenderWorker(
            config, gpx, Path(registry) if registry else None, self
        )
        self._worker.succeeded.connect(self._report_success)
        self._worker.failed.connect(self._report_failure)
        self._worker.finished.connect(self._render_finished)
        self._worker.start()

    def closeEvent(self, event: QCloseEvent | None) -> None:  # ty: ignore[invalid-method-override]
        """Ask before a close would kill a render in flight.

        The suppression is because PyQt's stub names this parameter ``a0`` and
        treats a rename as a keyword-incompatible override. Qt only ever calls
        it positionally, so ``event`` is safe and far more readable.
        """
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Render in progress",
                "A render is still running. Quit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                if event is not None:
                    event.ignore()
                return
            self._worker.wait()
        self._detach_logging()
        if event is not None:
            event.accept()

    # -- internals ----------------------------------------------------------

    def _widget_values(self) -> dict[str, Any]:
        """Read every widget into the field names ``RenderConfig`` expects."""
        return {
            "style": self.style_combo.currentText(),
            "tiff": _optional_path(self.tiff_edit.text()),
            "duration": self.duration_spin.value(),
            "hold": self.hold_spin.value(),
            "fps": self.fps_spin.value(),
            "size": self.size_combo.currentText(),
            "dpi": self.dpi_spin.value(),
            "margin": self.margin_spin.value(),
            "bounds": _optional_bounds(self.bounds_edit.text()),
            "logo_start": _text(self.logo_start_edit.text()),
            "logo_end": _text(self.logo_end_edit.text()),
            "logo_marker": _text(self.logo_marker_edit.text()),
            "logo_size_px": _optional_int(self.logo_size_spin.value()),
            "logo_plate_padding": self.logo_padding_spin.value(),
            "out": _optional_path(self.out_edit.text()),
            "output_dir": Path(self.output_dir_edit.text().strip() or "output"),
            "force": self.force_check.isChecked(),
            "appearance": {
                field: self.color_buttons[field].text() for field, _ in STYLE_COLORS
            }
            | {"font": self.font_edit.text().strip() or Style().font},
            "gif": {
                "enabled": self.gif_check.isChecked(),
                "size": self.gif_size_edit.text().strip(),
                "fps": self.gif_fps_spin.value(),
                "colors": int(self.gif_colors_combo.currentText()),
                "dither": self.gif_dither_check.isChecked(),
                "loop": self.gif_loop_spin.value(),
            },
            "profile": self.profile_combo.currentText(),
            "profile_width": self.profile_width_spin.value(),
            "profile_height": self.profile_height_spin.value(),
            "chart_video": self.chart_video_check.isChecked(),
        }

    def _pick_color(self, field: str) -> None:
        """Open the colour dialog and restyle the swatch to match."""
        button = self.color_buttons[field]
        chosen = QColor.fromString(button.text())
        color = QColorDialog.getColor(chosen, self, f"Choose {field}")
        if not color.isValid():
            return
        button.setText(color.name())
        button.setStyleSheet(f"background-color: {color.name()}")

    def _pick_gpx(self) -> None:
        """Open a file dialog for the track, seeded with what is already typed."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a GPX file",
            self.gpx_edit.text(),
            "GPX (*.gpx);;All files (*)",
        )
        if path:
            self.gpx_edit.setText(path)

    def _pick_into(self, edit: QLineEdit, pattern: str) -> None:
        """Open a file dialog and put the result in ``edit`` if one was chosen."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a file", edit.text(), pattern
        )
        if path:
            edit.setText(path)

    def _form(self, label: str, widget: Any) -> QFormLayout:
        """A one-row form, whether ``widget`` is a widget or a layout.

        Callers mix :class:`QLineEdit` and :class:`QHBoxLayout` freely; this is
        what lets them without branching at every call site.
        """
        layout = QFormLayout()
        if isinstance(widget, QWidget):
            layout.addRow(QLabel(label), widget)
        else:
            layout.addRow(QLabel(label))
            layout.addRow(widget)
        return layout

    def _tab(self, body: QVBoxLayout) -> QWidget:
        page = QWidget()
        page.setLayout(body)
        return page

    def _set_log_level(self, level: str) -> None:
        """Honour the log pane's level dropdown for the whole application."""
        logging.getLogger().setLevel(getattr(logging, level, logging.INFO))

    def _append_log(self, message: str) -> None:
        """Add a line to the log pane, on the GUI thread."""
        self.log_view.appendPlainText(message)

    def _report_success(self, out_path: str) -> None:
        """Tell the user where the video landed.

        The log pane already carries the pipeline's own ``Done:`` line, so this
        only sets the status text -- appending here too would show every path
        twice.
        """
        self.status_label.setText(f"Wrote {out_path}")

    def _report_failure(self, message: str) -> None:
        """Show a failure without taking the window down with it."""
        self.status_label.setText(message)
        self._append_log(f"ERROR: {message}")

    def _render_finished(self) -> None:
        """Re-enable the controls once the worker is done."""
        self.render_button.setEnabled(True)
        self.progress.setVisible(False)


class _LogBridge(QObject):
    """Carries log messages from the render thread to the GUI thread.

    A signal rather than a direct call because the handler that emits it runs on
    whichever thread is logging -- usually the render worker, sometimes the GUI
    thread. Qt queues the delivery, so the widget is only ever touched from the
    thread that owns it.
    """

    message = pyqtSignal(str)


def _as_text(value: object) -> str:
    """Render an optional path-like field as text for a line edit."""
    return "" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    """Launch the GUI.

    Args:
        argv: Unused. Accepted so the signature matches the CLI's ``main`` and
            so the console-script entry point is interchangeable with it; the
            widgets *are* the interface, so there is nothing to parse.

    Reuses an existing ``QApplication`` rather than insisting on its own: Qt
    allows one per process and constructing a second is undefined behaviour that
    segfaults, which would bite anyone embedding this in a larger Qt program.

    Returns:
        The Qt exit code.
    """
    app = QApplication.instance() or QApplication(
        sys.argv if argv is None else [sys.argv[0], *argv]
    )
    app.setApplicationName("gpx-animate")

    window = MainWindow()
    window.show()
    return app.exec()
