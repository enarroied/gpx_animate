"""The config layers above the defaults, and the schema they are checked against.

SPECS section 5 stacks four layers below the CLI flags: the shipped defaults, a
user TOML, a project TOML, and ``GPX_ANIMATE_*`` environment variables. This
module is only responsible for *reading* a layer and turning it into a nested
dictionary of overrides, keyed by the dotted config path (``appearance.font``).
``loader`` stacks them and validates the result.

Two deliberate choices, both about failing loudly:

- An unknown key is an error, not a warning. A typo like ``durtaion = 10``
  that is silently ignored is the kind of thing that costs an afternoon.
  The same applies to the environment namespace, which is ours to own.
- A missing file is not an error. Every user on Earth has no
  ``~/.config/gpx-animate/config.toml``, and that has to be the normal case.

The environment names are derived from the same field list the TOML keys are
validated against, so adding a field to the domain types makes it settable in
every layer at once. There is no second list to keep in sync.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomllib

from gpx_animate.domain.render_config import GifConfig
from gpx_animate.domain.render_config import RenderConfig
from gpx_animate.domain.style import Style


ENV_PREFIX = "GPX_ANIMATE_"
"""Namespace for the environment layer. Every variable must name a real key."""

USER_CONFIG_NAME = "config.toml"
"""Filename inside the user's config directory."""

PROJECT_CONFIG_NAME = "gpx-animate.toml"
"""Filename looked for in the directory the command was run from."""

APPEARANCE_GROUP = "appearance"
GIF_GROUP = "gif"
"""Config group holding the :class:`~gpx_animate.domain.style.Style` fields."""


class ConfigError(ValueError):
    """A config file or environment variable could not be turned into settings."""


def config_keys() -> tuple[str, ...]:
    """Every dotted key the config layers accept.

    Includes the ``appearance`` group name itself, because that is what a TOML
    table header says. Use :func:`settable_keys` where the group is not a value
    in its own right, such as the environment layer and error messages.

    Derived from the dataclass fields, so a new domain field is settable from
    TOML and the environment without touching this module.

    Returns:
        Top-level fields, then ``appearance.*`` for each :class:`Style` field.
    """
    top_level = tuple(field.name for field in dataclasses.fields(RenderConfig))
    nested = tuple(
        f"{APPEARANCE_GROUP}.{field.name}" for field in dataclasses.fields(Style)
    ) + tuple(f"{GIF_GROUP}.{field.name}" for field in dataclasses.fields(GifConfig))
    return top_level + nested


def settable_keys() -> tuple[str, ...]:
    """The keys that can be *given a value*, i.e. everything but the groups.

    ``appearance`` is a table header in TOML and nothing at all in the
    environment; letting ``GPX_ANIMATE_APPEARANCE`` through would replace the
    whole :class:`Style` with a string, which then fails far from the cause.

    Returns:
        The keys an assignment may name.
    """
    return tuple(key for key in config_keys() if "." in key or key != APPEARANCE_GROUP)


def env_key_map() -> dict[str, str]:
    """Map the environment suffix for each key to its dotted path.

    ``appearance.bg_color`` becomes ``APPEARANCE_BG_COLOR``, matching SPECS
    section 5: nested groups are env-var sub-keys. The whole suffix is matched,
    never a prefix, so ``LOGO_START`` and ``LOGO_MARKER`` stay distinct.

    Returns:
        Uppercase env suffix to dotted config path.
    """
    return {key.replace(".", "_").upper(): key for key in settable_keys()}


def user_config_path() -> Path:
    """Where the per-user TOML lives.

    Returns:
        ``~/.config/gpx-animate/config.toml``, which need not exist.
    """
    return Path.home() / ".config" / "gpx-animate" / USER_CONFIG_NAME


def read_toml_layer(path: Path) -> dict[str, Any]:
    """Read one TOML file into a nested override dictionary.

    Args:
        path: The file to read.

    Returns:
        The file's tables, or an empty dictionary if it does not exist.

    Raises:
        ConfigError: If the file is not valid TOML, or is not a table.
    """
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    return data


def flatten_toml(data: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
    """Flatten a nested TOML table into dotted override keys.

    One level of nesting only, which is all the schema has: a top-level key, or
    the ``appearance`` group.

    Args:
        data: Tables as :func:`read_toml_layer` returned them.
        origin: How to name the source in an error message.

    Returns:
        Dotted key to raw value, e.g. ``{"appearance.font": "Inter"}``.

    Raises:
        ConfigError: If a key is unknown, or a group is not a table.
    """
    known = set(config_keys())
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if key in (APPEARANCE_GROUP, GIF_GROUP):
            if not isinstance(value, Mapping):
                raise ConfigError(f"{origin}: [{key}] must be a table")
            for sub_key, sub_value in value.items():
                dotted = f"{key}.{sub_key}"
                if dotted not in known:
                    raise ConfigError(_unknown_message(dotted, origin))
                flat[dotted] = sub_value
        elif key in known:
            flat[key] = value
        else:
            raise ConfigError(_unknown_message(key, origin))
    return flat


def read_env_layer(environ: Mapping[str, str]) -> dict[str, Any]:
    """Read ``GPX_ANIMATE_*`` variables into dotted override keys.

    Args:
        environ: The environment to read. Defaults to :data:`os.environ` at the
            call site; passed in so tests do not need to patch the real one.

    Returns:
        Dotted key to raw string value.

    Raises:
        ConfigError: If a variable in the namespace is not a known key.
    """
    mapping = env_key_map()
    overrides: dict[str, Any] = {}
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        suffix = name[len(ENV_PREFIX) :]
        dotted = mapping.get(suffix)
        if dotted is None:
            raise ConfigError(_unknown_message(suffix, "the environment"))
        if value.strip() == "":
            # An empty variable is how a shell says "unset this", not "set it
            # to the empty string", which almost no key could accept anyway.
            continue
        overrides[dotted] = value
    return overrides


def default_environ() -> Mapping[str, str]:
    """Return the process environment.

    Returns:
        A snapshot of :data:`os.environ`, read at call time.
    """
    return dict(os.environ)


def _unknown_message(key: str, origin: str) -> str:
    """Explain an unknown key, and list what is allowed."""
    allowed = ", ".join(settable_keys())
    return f"{origin} has no setting {key!r}; valid keys are {allowed}"
