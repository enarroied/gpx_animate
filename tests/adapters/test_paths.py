"""Locating the program, the bundled ffmpeg, and the output directory.

The distinction between "where the program is" and "where output goes" is the
whole point of this module, so most of these tests are about the cases where the
two answers differ.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gpx_animate.adapters.paths import application_dir
from gpx_animate.adapters.paths import output_dir_base
from gpx_animate.adapters.paths import resolve_output_dir


@pytest.fixture
def frozen(monkeypatch):
    """Pretend to be a PyInstaller build living in ``exe_dir``."""

    def _frozen(exe_dir, argv=("gpx-animate-gui.exe",)):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "gpx-animate-gui.exe"))
        monkeypatch.setattr(sys, "argv", list(argv))
        return exe_dir

    return _frozen


@pytest.fixture
def not_frozen(monkeypatch):
    """Pretend to be an ordinary source checkout run from ``cwd``."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["/home/dev/project/gpx-animate-gui"])
    return Path("C:/Users/brother/AppData/Local/Temp")


class TestApplicationDir:
    def test_frozen_it_is_the_executables_directory(self, frozen, tmp_path):
        # The fixture must run first: it is what patches sys.executable, and
        # application_dir() reads it.
        exe_dir = frozen(tmp_path / "app").resolve()
        assert application_dir() == exe_dir

    def test_frozen_it_ignores_the_working_directory(
        self, frozen, tmp_path, monkeypatch
    ):
        """The whole bug: a double-clicked exe starts in System32, not here."""
        monkeypatch.chdir(tmp_path)
        exe_dir = frozen(tmp_path / "app").resolve()
        assert application_dir() == exe_dir

    @pytest.mark.usefixtures("not_frozen")
    def test_source_checkout_it_is_the_scripts_directory(self):
        assert application_dir() == Path("/home/dev/project")

    def test_no_argv0_it_falls_back_to_the_working_directory(
        self, monkeypatch, tmp_path
    ):
        """python -c and embedded interpreters have no script to point at."""
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(sys, "argv", [])
        monkeypatch.chdir(tmp_path)
        assert application_dir() == tmp_path


class TestOutputDirBase:
    def test_frozen_it_is_the_executables_directory(self, frozen, tmp_path):
        exe_dir = frozen(tmp_path / "app").resolve()
        assert output_dir_base() == exe_dir

    @pytest.mark.usefixtures("not_frozen")
    def test_source_checkout_it_is_the_working_directory(self, monkeypatch, tmp_path):
        """Deliberately NOT the script directory: that would be .venv/bin."""
        monkeypatch.chdir(tmp_path)
        assert output_dir_base() == tmp_path


class TestResolveOutputDir:
    @pytest.mark.usefixtures("not_frozen")
    def test_not_frozen_a_relative_directory_is_untouched(self, monkeypatch, tmp_path):
        """No-op, so the CLI's relative output and printed paths do not move."""
        monkeypatch.chdir(tmp_path)
        assert resolve_output_dir(Path("output")) == Path("output")

    def test_an_absolute_directory_is_untouched_either_way(self, frozen, tmp_path):
        frozen(tmp_path / "app")
        assert resolve_output_dir(tmp_path / "elsewhere") == tmp_path / "elsewhere"

    def test_frozen_a_relative_directory_moves_beside_the_program(
        self, frozen, tmp_path
    ):
        exe_dir = frozen(tmp_path / "app")
        assert resolve_output_dir(Path("output")) == exe_dir.resolve() / "output"
