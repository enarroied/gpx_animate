"""The logo registry and the image reading behind it.

A ``--logo-*`` source is either a name from ``logos/registry.yaml`` or a path to
an image, and US-5 wants both to work with the same flag. Deciding which one it
is, reading the registry and reading the pixels are all filesystem work, so
they live here, in the adapter, and the application only ever sees a resolved
:class:`~gpx_animate.application.ports.Logo`.

The registry is parsed lazily. A missing ``logos/registry.yaml`` is not an
error, because every flag also accepts a bare path, and a registry that is
malformed is likewise not read until a name actually has to be looked up in it.
Eager parsing would fail a run that never mentions a name, for a file the run
does not use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.image as mpimg
import yaml

from gpx_animate.application.errors import LogoFileNotFoundError
from gpx_animate.application.errors import LogoRegistryError
from gpx_animate.application.errors import LogoUnreadableError
from gpx_animate.application.errors import UnknownLogoError
from gpx_animate.application.ports import Logo
from gpx_animate.domain.logo import DEFAULT_LOGO_ANCHOR
from gpx_animate.domain.logo import DEFAULT_LOGO_SIZE_PX
from gpx_animate.domain.logo import LOGO_ANCHORS


logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("logos") / "registry.yaml"
"""Where the registry is looked for when ``--logo-registry`` is not given.

Relative to the working directory, like ``gpx-animate.toml`` and ``--out``'s
``output_dir``, so a project that ships its own logos is found by running the
tool inside it.
"""

REGISTRY_ENTRY_KEYS = frozenset({"file", "anchor", "default_size_px"})
"""Keys one registry entry may carry. An unknown one is a typo, and is reported
as an error rather than ignored, for the same reason the config layer refuses
to ignore a misspelt key: a silently dropped ``anchor`` would draw the logo in
the wrong place with no explanation.
"""


@dataclass(frozen=True)
class LogoEntry:
    """One row of ``logos/registry.yaml``.

    Args:
        name: The key it is registered under, as typed on the command line.
        file: Absolute or registry-relative path to the image.
        anchor: A key into :data:`~gpx_animate.domain.logo.LOGO_ANCHORS`.
        size_px: Width in device pixels.
    """

    name: str
    file: Path
    anchor: str
    size_px: int


class LogoRegistry:
    """The names in a registry file, and the files behind them.

    Args:
        path: Registry to read. Defaults to
            :data:`DEFAULT_REGISTRY_PATH`; the file need not exist.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = DEFAULT_REGISTRY_PATH if path is None else path
        self._entries: dict[str, LogoEntry] | None = None

    @property
    def exists(self) -> bool:
        """Whether a registry file is actually on disk."""
        return self.path.exists()

    def names(self) -> tuple[str, ...]:
        """Every registered logo name, sorted, for use in error messages."""
        return tuple(sorted(self._load()))

    def lookup(self, name: str) -> LogoEntry | None:
        """Find one entry by name.

        Args:
            name: The registered name.

        Returns:
            The entry, or ``None`` if nothing is registered under that name.
        """
        return self._load().get(name)

    def _load(self) -> dict[str, LogoEntry]:
        if self._entries is None:
            self._entries = self._parse()
            logger.debug("Read %d logo(s) from %s", len(self._entries), self.path)
        return self._entries

    def _parse(self) -> dict[str, LogoEntry]:
        if not self.path.exists():
            return {}
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise LogoRegistryError(
                f"{self.path} is not valid YAML: {error}"
            ) from error
        if raw is None:
            return {}
        if not isinstance(raw, dict) or "logos" not in raw:
            raise LogoRegistryError(
                f"{self.path}: expected a top-level 'logos:' mapping of "
                f"name to entry, got {type(raw).__name__}"
            )
        logos = raw["logos"]
        if logos is None:
            return {}
        if not isinstance(logos, dict):
            raise LogoRegistryError(
                f"{self.path}: 'logos' must be a mapping of name to entry, got "
                f"{type(logos).__name__}"
            )
        return {
            str(name): self._entry(str(name), value) for name, value in logos.items()
        }

    def _entry(self, name: str, value: Any) -> LogoEntry:
        where = f"{self.path}: logo {name!r}"
        if not isinstance(value, dict):
            raise LogoRegistryError(
                f"{where} must be a mapping, got {type(value).__name__}"
            )
        unknown = set(value) - REGISTRY_ENTRY_KEYS
        if unknown:
            raise LogoRegistryError(
                f"{where} has unknown key(s) {sorted(unknown)}; valid keys are "
                f"{sorted(REGISTRY_ENTRY_KEYS)}"
            )
        file = value.get("file")
        if not isinstance(file, str) or not file.strip():
            raise LogoRegistryError(f"{where} needs a 'file:' naming the image to draw")
        anchor = value.get("anchor", DEFAULT_LOGO_ANCHOR)
        if anchor not in LOGO_ANCHORS:
            raise LogoRegistryError(
                f"{where} has anchor {anchor!r}; must be one of {sorted(LOGO_ANCHORS)}"
            )
        size_px = value.get("default_size_px", DEFAULT_LOGO_SIZE_PX)
        if isinstance(size_px, bool) or not isinstance(size_px, int) or size_px <= 0:
            raise LogoRegistryError(
                f"{where} has default_size_px {size_px!r}; must be a positive integer"
            )
        return LogoEntry(
            name=name,
            # A registry names its own neighbours, so a relative 'file:' is
            # resolved against the registry's directory, not the cwd. That way
            # a project can move its logos directory without editing paths.
            file=self.path.parent / file,
            anchor=anchor,
            size_px=size_px,
        )


def _looks_like_path(source: str) -> bool:
    """Whether a source reads as a file path rather than a registry name.

    A source that exists is unambiguous either way, so this only decides which
    *error* a miss produces. ``brand/logo.png`` is a mistyped path far more
    often than a name, and reporting it as an unknown logo would send the user
    to the registry instead of to their own filesystem.
    """
    return "/" in source or "\\" in source or bool(Path(source).suffix)


class PngLogoLoader:
    """Resolves ``--logo-*`` sources to drawable logos.

    Args:
        registry: Where names are looked up. Defaults to a registry at
            :data:`DEFAULT_REGISTRY_PATH`.
    """

    def __init__(self, registry: LogoRegistry | None = None) -> None:
        self.registry = LogoRegistry() if registry is None else registry

    def resolve(self, source: str) -> Logo:
        """Read a logo named by a registry name or a path.

        An existing file always wins over a name of the same spelling, so a
        ``--logo-start car`` with a file called ``car`` in the cwd draws the
        file. Explicit is the better reading of that ambiguity: the user named a
        thing that is unambiguously there.

        Args:
            source: A registered name, or a path to an image.

        Returns:
            The image with the placement to draw it at.

        Raises:
            UnknownLogoError: The source is neither an existing file nor a name
                the registry knows.
            LogoFileNotFoundError: The source reads as a path but is missing,
                or a registry entry points at a file that is not there.
            LogoUnreadableError: The file exists but matplotlib could not read
                it as an image.
        """
        entry, path = self._locate(source)
        if not path.is_file():
            # _locate only hands back a missing file via a registry entry: an
            # existing file always wins name-vs-path resolution, and a path-like
            # miss raises inside _locate. So a miss here means the registry
            # points at a neighbour that is not there -- a project bug, not a
            # mistyped command line.
            assert entry is not None
            raise LogoFileNotFoundError(
                f"logo {source!r} is registered as {entry.file}, which does not exist"
            )
        try:
            image = mpimg.imread(path)
        except (OSError, ValueError) as error:
            raise LogoUnreadableError(
                f"{path} could not be read as an image: {error}"
            ) from error
        logo = Logo(
            image=image,
            anchor=entry.anchor if entry is not None else DEFAULT_LOGO_ANCHOR,
            size_px=entry.size_px if entry is not None else DEFAULT_LOGO_SIZE_PX,
            source=source,
        )
        logger.debug(
            "Resolved logo %r to %s (anchor=%s, %dpx)",
            source,
            path,
            logo.anchor,
            logo.size_px,
        )
        return logo

    def _locate(self, source: str) -> tuple[LogoEntry | None, Path]:
        """Decide whether a source is a path or a name, and find the file.

        Args:
            source: A registered name, or a path to an image.

        Returns:
            The registry entry, if the source was a name, and the file to read.

        Raises:
            UnknownLogoError: The source is neither an existing file nor a known
                name.
            LogoFileNotFoundError: The source reads as a path but is missing.
        """
        candidate = Path(source).expanduser()
        if candidate.is_file():
            return None, candidate
        if _looks_like_path(source):
            raise LogoFileNotFoundError(f"logo file {source!r} does not exist")
        entry = self.registry.lookup(source)
        if entry is None:
            raise UnknownLogoError(self._unknown_message(source))
        return entry, entry.file

    def _unknown_message(self, source: str) -> str:
        """Explain a name that resolved to nothing, naming what was available."""
        if not self.registry.exists:
            return (
                f"logo {source!r} is not a file, and there is no registry at "
                f"{self.registry.path}. Pass a path to an image, or create that "
                f"file; see --logo-registry."
            )
        known = self.registry.names()
        if not known:
            return (
                f"logo {source!r} is not a file, and {self.registry.path} "
                f"registers no logos."
            )
        return (
            f"logo {source!r} is not a file, and is not in "
            f"{self.registry.path}. Known logos: {', '.join(known)}."
        )
