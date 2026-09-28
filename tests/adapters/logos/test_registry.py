"""The logo registry and the loader that reads through it."""

from __future__ import annotations

from pathlib import Path

import matplotlib


matplotlib.use("Agg")

import matplotlib.image as mpimg  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from gpx_animate.adapters.logos.registry import DEFAULT_REGISTRY_PATH  # noqa: E402
from gpx_animate.adapters.logos.registry import LogoRegistry  # noqa: E402
from gpx_animate.adapters.logos.registry import PngLogoLoader  # noqa: E402
from gpx_animate.application.errors import LogoFileNotFoundError  # noqa: E402
from gpx_animate.application.errors import LogoRegistryError  # noqa: E402
from gpx_animate.application.errors import LogoUnreadableError  # noqa: E402
from gpx_animate.application.errors import UnknownLogoError  # noqa: E402
from gpx_animate.application.ports import Logo  # noqa: E402
from gpx_animate.application.ports import LogoLoader  # noqa: E402
from gpx_animate.domain.logo import DEFAULT_LOGO_ANCHOR  # noqa: E402
from gpx_animate.domain.logo import DEFAULT_LOGO_SIZE_PX  # noqa: E402


@pytest.fixture
def registry_dir(tmp_path, logo_png):
    """A logos/ directory holding one image and a registry naming it."""
    logos = tmp_path / "logos"
    logos.mkdir()
    mpimg.imsave(logos / "car.png", np.zeros((16, 16, 4), dtype=float))
    (logos / "registry.yaml").write_text(
        "logos:\n"
        "  car:\n"
        "    file: car.png\n"
        "    anchor: center\n"
        "    default_size_px: 64\n",
        encoding="utf-8",
    )
    assert logo_png.exists(), "the shared logo fixture is missing"
    return logos


def write_registry(path, text):
    """Write a registry body and return the file, for the error cases."""
    path.write_text(text, encoding="utf-8")
    return path


class TestRegistryParsing:
    def test_reads_a_name_into_an_entry(self, registry_dir):
        entry = LogoRegistry(registry_dir / "registry.yaml").lookup("car")
        assert entry is not None
        assert entry.name == "car"
        assert entry.file == registry_dir / "car.png"
        assert entry.anchor == "center"
        assert entry.size_px == 64

    def test_a_relative_file_resolves_against_the_registry(self, tmp_path):
        """A registry names its own neighbours, so a project can move them."""
        nested = tmp_path / "assets" / "registry.yaml"
        nested.parent.mkdir()
        write_registry(nested, "logos:\n  car:\n    file: ../car.png\n")
        entry = LogoRegistry(nested).lookup("car")
        assert entry is not None
        assert entry.file == tmp_path / "assets" / "../car.png"

    def test_anchor_and_size_fall_back_to_the_defaults(self, tmp_path):
        """A bare entry is legal; only a bare path is a different case."""
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: c.png\n"
        )
        entry = LogoRegistry(registry).lookup("car")
        assert entry is not None
        assert entry.anchor == DEFAULT_LOGO_ANCHOR
        assert entry.size_px == DEFAULT_LOGO_SIZE_PX

    def test_lists_the_known_names(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml",
            "logos:\n  zebra:\n    file: z.png\n  ant:\n    file: a.png\n",
        )
        assert LogoRegistry(registry).names() == ("ant", "zebra")

    def test_an_unknown_name_is_simply_absent(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: c.png\n"
        )
        assert LogoRegistry(registry).lookup("bike") is None

    def test_a_missing_registry_is_empty_not_an_error(self, tmp_path):
        registry = LogoRegistry(tmp_path / "absent.yaml")
        assert registry.exists is False
        assert registry.names() == ()
        assert registry.lookup("car") is None

    def test_an_empty_registry_file_is_empty(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "")
        assert LogoRegistry(registry).names() == ()

    def test_a_null_logos_key_is_empty(self, tmp_path):
        """`logos:` with nothing under it is an empty registry, not a crash."""
        registry = write_registry(tmp_path / "r.yaml", "logos:\n")
        assert LogoRegistry(registry).names() == ()

    def test_the_default_path_is_under_logos(self):
        assert Path("logos") / "registry.yaml" == DEFAULT_REGISTRY_PATH

    def test_the_default_registry_is_used_when_none_is_given(self):
        assert LogoRegistry().path == DEFAULT_REGISTRY_PATH


class TestRegistryErrors:
    """A typo in a registry is reported, never quietly ignored."""

    def test_unparseable_yaml_is_reported(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "logos: [unclosed\n")
        with pytest.raises(LogoRegistryError, match="not valid YAML"):
            LogoRegistry(registry).names()

    def test_a_missing_logos_key_is_reported(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "something_else: 1\n")
        with pytest.raises(LogoRegistryError, match="top-level 'logos:'"):
            LogoRegistry(registry).names()

    def test_a_non_mapping_document_is_reported(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "just a string\n")
        with pytest.raises(LogoRegistryError, match="top-level 'logos:'"):
            LogoRegistry(registry).names()

    def test_a_non_mapping_logos_is_reported(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "logos:\n  - car\n")
        with pytest.raises(LogoRegistryError, match="'logos' must be a mapping"):
            LogoRegistry(registry).names()

    def test_a_non_mapping_entry_is_reported(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "logos:\n  car: car.png\n")
        with pytest.raises(LogoRegistryError, match="must be a mapping"):
            LogoRegistry(registry).names()

    def test_an_unknown_key_is_reported_with_the_valid_ones(self, tmp_path):
        """A misspelt `anchors:` would otherwise draw the logo in the wrong
        place, which is exactly the silent failure this repo refuses."""
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: c.png\n    anchors: top\n"
        )
        with pytest.raises(LogoRegistryError, match=r"unknown key\(s\) \['anchors'\]"):
            LogoRegistry(registry).names()

    def test_a_missing_file_key_is_reported(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    anchor: top\n"
        )
        with pytest.raises(LogoRegistryError, match="needs a 'file:'"):
            LogoRegistry(registry).names()

    def test_a_blank_file_key_is_reported(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: '  '\n"
        )
        with pytest.raises(LogoRegistryError, match="needs a 'file:'"):
            LogoRegistry(registry).names()

    def test_an_unknown_anchor_is_reported(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: c.png\n    anchor: middle\n"
        )
        with pytest.raises(LogoRegistryError, match="anchor 'middle'"):
            LogoRegistry(registry).names()

    @pytest.mark.parametrize(
        ("size", "as_yaml"),
        [
            (0, "0"),
            (-8, "-8"),
            (4.5, "4.5"),
            (True, "true"),
            ("48", '"48"'),
        ],
    )
    def test_a_bad_size_is_reported(self, tmp_path, size, as_yaml):
        """Quoted on purpose: bare 48 is a valid int, and must be accepted."""
        registry = write_registry(
            tmp_path / "r.yaml",
            f"logos:\n  car:\n    file: c.png\n    default_size_px: {as_yaml}\n",
        )
        with pytest.raises(LogoRegistryError, match="must be a positive integer"):
            LogoRegistry(registry).names()

    def test_a_plain_integer_size_is_accepted(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml",
            "logos:\n  car:\n    file: c.png\n    default_size_px: 48\n",
        )
        entry = LogoRegistry(registry).lookup("car")
        assert entry is not None
        assert entry.size_px == 48

    def test_the_path_is_in_the_message(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "logos:\n  car: 3\n")
        with pytest.raises(LogoRegistryError, match=str(registry)):
            LogoRegistry(registry).names()


class TestResolving:
    def test_a_name_resolves_to_its_registered_placement(self, registry_dir):
        logo = PngLogoLoader(LogoRegistry(registry_dir / "registry.yaml")).resolve(
            "car"
        )
        assert logo.anchor == "center"
        assert logo.size_px == 64
        assert logo.source == "car"

    def test_a_path_resolves_with_the_defaults(self, logo_png):
        """A bare path has no registry entry, so it takes the domain defaults."""
        logo = PngLogoLoader().resolve(str(logo_png))
        assert logo.anchor == DEFAULT_LOGO_ANCHOR
        assert logo.size_px == DEFAULT_LOGO_SIZE_PX

    def test_reads_the_image(self, registry_dir):
        logo = PngLogoLoader(LogoRegistry(registry_dir / "registry.yaml")).resolve(
            "car"
        )
        assert isinstance(logo.image, np.ndarray)
        assert logo.image.shape[:2] == (16, 16)

    def test_keeps_the_alpha_channel(self, logo_png):
        """A logo with transparency is the point; RGB-only would flatten it."""
        assert PngLogoLoader().resolve(str(logo_png)).image.shape[-1] == 4

    def test_is_normalised_for_imshow(self, logo_png):
        """matplotlib scales to 0..1 floats, and the renderer draws it directly."""
        image = PngLogoLoader().resolve(str(logo_png)).image
        assert image.min() >= 0.0
        assert image.max() <= 1.0

    def test_reports_the_aspect_from_the_pixels(self, tmp_path):
        """A wide file keeps its shape, so a 48px width is not a 48px square."""
        path = tmp_path / "wide.png"
        mpimg.imsave(path, np.zeros((8, 16, 4), dtype=float))
        assert PngLogoLoader().resolve(str(path)).aspect == pytest.approx(0.5)

    def test_a_degenerate_image_reports_an_aspect_of_one(self):
        """Guards the division; a zero-width array is not drawable anyway."""
        degenerate = Logo(
            image=np.zeros((4, 0, 4)), anchor="center", size_px=8, source="x"
        )
        assert degenerate.aspect == 1.0

    def test_an_existing_file_beats_a_name_of_the_same_spelling(
        self, tmp_path, logo_png
    ):
        """Explicit wins: a file that is unambiguously there is what was meant."""
        (tmp_path / "car").write_bytes(logo_png.read_bytes())
        registry = write_registry(
            tmp_path / "r.yaml",
            "logos:\n  car:\n    file: nowhere.png\n    anchor: top\n",
        )
        loader = PngLogoLoader(LogoRegistry(registry))
        with pytest.MonkeyPatch.context() as patch:
            patch.chdir(tmp_path)
            logo = loader.resolve("car")
        assert logo.anchor == DEFAULT_LOGO_ANCHOR
        assert logo.size_px == DEFAULT_LOGO_SIZE_PX

    def test_expands_a_user_home_path(self, tmp_path, logo_png, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        home_logo = tmp_path / "h.png"
        mpimg.imsave(home_logo, np.zeros((8, 8, 4), dtype=float))
        assert PngLogoLoader().resolve("~/h.png").image.shape[:2] == (8, 8)

    def test_the_loader_uses_the_default_registry_when_given_none(self):
        assert isinstance(PngLogoLoader().registry, LogoRegistry)
        assert PngLogoLoader().registry.path == DEFAULT_REGISTRY_PATH

    def test_satisfies_the_logo_port(self, registry_dir):
        assert isinstance(PngLogoLoader(LogoRegistry()), LogoLoader)


class TestResolveErrors:
    def test_a_missing_path_says_the_file_is_missing(self, tmp_path):
        with pytest.raises(LogoFileNotFoundError, match="does not exist"):
            PngLogoLoader().resolve(str(tmp_path / "nope.png"))

    def test_a_missing_path_is_not_called_an_unknown_name(self, tmp_path):
        """A typo'd path must not send the user looking in the registry."""
        with pytest.raises(LogoFileNotFoundError, match="nope.png"):
            PngLogoLoader().resolve("logos/nope.png")

    def test_a_windows_style_path_is_read_as_a_path(self):
        with pytest.raises(LogoFileNotFoundError):
            PngLogoLoader().resolve("logos\\nope.png")

    def test_a_name_with_no_registry_names_the_path(self, tmp_path):
        registry = tmp_path / "logos" / "registry.yaml"
        loader = PngLogoLoader(LogoRegistry(registry))
        with pytest.raises(UnknownLogoError, match="no registry at"):
            loader.resolve("car")
        assert str(registry) in str(
            pytest.raises(UnknownLogoError, loader.resolve, "car").value
        )

    def test_a_name_with_no_registry_suggests_the_flag(self, tmp_path):
        loader = PngLogoLoader(LogoRegistry(tmp_path / "logos" / "registry.yaml"))
        with pytest.raises(UnknownLogoError, match="--logo-registry"):
            loader.resolve("car")

    def test_an_unknown_name_lists_the_known_ones(self, tmp_path):
        registry = write_registry(
            tmp_path / "r.yaml",
            "logos:\n  zebra:\n    file: z.png\n  ant:\n    file: a.png\n",
        )
        with pytest.raises(UnknownLogoError, match="ant, zebra"):
            PngLogoLoader(LogoRegistry(registry)).resolve("car")

    def test_an_empty_registry_is_reported_as_such(self, tmp_path):
        registry = write_registry(tmp_path / "r.yaml", "logos:\n")
        with pytest.raises(UnknownLogoError, match="registers no logos"):
            PngLogoLoader(LogoRegistry(registry)).resolve("car")

    def test_an_entry_whose_file_is_gone_says_so(self, tmp_path):
        """Distinct from an unknown name: the name was right, the file is not."""
        registry = write_registry(
            tmp_path / "r.yaml", "logos:\n  car:\n    file: gone.png\n"
        )
        with pytest.raises(LogoFileNotFoundError, match="is registered as"):
            PngLogoLoader(LogoRegistry(registry)).resolve("car")

    def test_a_file_that_is_not_an_image_is_reported(self, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("not a png", encoding="utf-8")
        with pytest.raises(LogoUnreadableError, match="could not be read as an image"):
            PngLogoLoader().resolve(str(notes))

    def test_a_directory_is_not_a_logo(self, tmp_path):
        with pytest.raises((LogoFileNotFoundError, LogoUnreadableError)):
            PngLogoLoader().resolve(str(tmp_path))
