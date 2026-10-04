"""Stack the config layers and hand back a validated RenderConfig.

The order is SPECS section 5, lowest first:

1. the shipped defaults
2. ``~/.config/gpx-animate/config.toml``
3. ``./gpx-animate.toml``
4. ``GPX_ANIMATE_*`` environment variables

The CLI flags are layer 5 and are applied by the adapter on top of whatever
this returns, so nothing here needs to know about argparse.

Values arriving from a file or the environment are strings, TOML numbers, or
TOML booleans; the dataclass wants ``float``, ``int``, ``Path`` and ``bool``.
Coercion happens here, before :meth:`RenderConfig.__post_init__` validates, so
a bad setting fails with a message naming the layer it came from rather than
as a confusing range error.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gpx_animate.config import layers
from gpx_animate.config.defaults import default_config
from gpx_animate.config.layers import APPEARANCE_GROUP
from gpx_animate.config.layers import GIF_GROUP
from gpx_animate.config.layers import PROJECT_CONFIG_NAME
from gpx_animate.config.layers import ConfigError
from gpx_animate.domain.bbox import Bbox
from gpx_animate.domain.bbox import parse_bounds
from gpx_animate.domain.render_config import RenderConfig


TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
FALSE_WORDS = frozenset({"0", "false", "no", "off"})
"""What a boolean may be spelled in the environment, where everything is text."""


def _to_bool(value: Any) -> bool:
    """Coerce a config value to a bool.

    Args:
        value: A real bool from TOML, or a word or digit from the environment.

    Returns:
        The boolean it names.

    Raises:
        ConfigError: If the text is neither true-ish nor false-ish.
    """
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ConfigError(
        f"{value!r} is not a boolean; use one of {sorted(TRUE_WORDS | FALSE_WORDS)}"
    )


def _to_path(value: Any) -> Path:
    """Coerce a config value to a Path."""
    return Path(str(value)).expanduser()


def _to_optional_path(value: Any) -> Path | None:
    """Coerce a config value to a Path, treating blank as unset.

    ``out = ""`` in TOML is a way of saying "no explicit destination" rather
    than "write to a file with no name", which would fail later and less
    clearly.
    """
    text = str(value).strip()
    return None if text == "" else Path(text).expanduser()


def _identity(value: Any) -> Any:
    """Pass a value through unchanged, for the string fields."""
    return value


def _to_bounds(value: Any) -> Bbox:
    """Coerce a config value to a bounds box.

    The value arrives as ``"min_lon,min_lat,max_lon,max_lat"`` in a file or the
    environment, or already as a :class:`Bbox` from a programmatic caller.
    """
    if isinstance(value, Bbox):
        return value
    return parse_bounds(str(value))


COERCERS: dict[str, Callable[[Any], Any]] = {
    "duration": float,
    "hold": float,
    "margin": float,
    "fps": int,
    "dpi": int,
    "logo_size_px": int,
    "logo_plate_padding": float,
    "force": _to_bool,
    "out": _to_optional_path,
    "output_dir": _to_path,
    "tiff": _to_optional_path,
    "bounds": _to_bounds,
    "gif.fps": int,
    "gif.colors": int,
    "gif.loop": int,
    "gif.dither": _to_bool,
    "gif.enabled": _to_bool,
    "profile_height": float,
    "profile_width": float,
    "chart_video": _to_bool,
}
"""How each non-string key is converted. Everything else is a string."""


def coerce_overrides(overrides: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
    """Convert raw override values to the types the domain expects.

    Args:
        overrides: Dotted key to raw value, as the layers produced them.
        origin: How to name the source in an error message.

    Returns:
        The same keys with values converted.

    Raises:
        ConfigError: If a value cannot be converted, e.g. ``fps = "many"``.
    """
    coerced: dict[str, Any] = {}
    for key, value in overrides.items():
        convert = COERCERS.get(key, _identity)
        try:
            coerced[key] = convert(value)
        except (TypeError, ValueError) as error:
            raise ConfigError(
                f"{origin}: {key} = {value!r} is invalid: {error}"
            ) from error
    return coerced


def apply_overrides(base: RenderConfig, overrides: Mapping[str, Any]) -> RenderConfig:
    """Return ``base`` with ``overrides`` applied.

    Overrides are dotted keys, so ``appearance.*`` are folded into a new
    :class:`~gpx_animate.domain.style.Style` rather than passed to the config.
    The result goes through :func:`dataclasses.replace`, which re-runs
    ``__post_init__`` and therefore re-validates the whole config.

    Args:
        base: The config to start from.
        overrides: Dotted key to already-coerced value.

    Returns:
        A new validated config. ``base`` is untouched.
    """
    top_level = {k: v for k, v in overrides.items() if "." not in k}
    appearance = {
        key.split(".", 1)[1]: value
        for key, value in overrides.items()
        if key.startswith(f"{APPEARANCE_GROUP}.")
    }
    gif = {
        key.split(".", 1)[1]: value
        for key, value in overrides.items()
        if key.startswith(f"{GIF_GROUP}.")
    }
    if isinstance(top_level.get(APPEARANCE_GROUP), Mapping):
        # Without this the dataclass field would be quietly replaced by a dict,
        # and the renderer would fail much later with a much worse message.
        raise ConfigError(
            f"{APPEARANCE_GROUP} must be given as dotted keys such as "
            f"{APPEARANCE_GROUP}.font, not as a nested table"
        )
    if isinstance(top_level.get(GIF_GROUP), Mapping):
        raise ConfigError(
            f"{GIF_GROUP} must be given as dotted keys such as "
            f"{GIF_GROUP}.fps, not as a nested table"
        )
    if appearance:
        top_level[APPEARANCE_GROUP] = dataclasses.replace(base.appearance, **appearance)
    if gif:
        top_level[GIF_GROUP] = dataclasses.replace(base.gif, **gif)
    return dataclasses.replace(base, **top_level)


def load_config(
    project_dir: Path,
    environ: Mapping[str, str] | None = None,
    *,
    user_path: Path | None = None,
) -> RenderConfig:
    """Resolve layers 1 to 4 into one config.

    Args:
        project_dir: Where to look for ``gpx-animate.toml``. The caller passes
            the working directory, rather than this reading it, so the layers
            are testable without changing process state.
        environ: The environment layer. Defaults to the process environment.
        user_path: Override for the user TOML location. Mainly for tests, which
            must not read the developer's real ``~/.config``.

    Returns:
        A validated config, ready for the CLI flags to be layered on top.

    Raises:
        ConfigError: If any layer has an unreadable file, an unknown key, or a
            value that cannot be coerced or fails validation.
    """
    config = default_config()

    for path in (
        user_path if user_path is not None else layers.user_config_path(),
        project_dir / PROJECT_CONFIG_NAME,
    ):
        origin = str(path)
        overrides = layers.flatten_toml(layers.read_toml_layer(path), origin=origin)
        config = apply_overrides(config, coerce_overrides(overrides, origin=origin))

    origin = "the environment"
    env_overrides = layers.read_env_layer(
        environ if environ is not None else layers.default_environ()
    )
    return apply_overrides(config, coerce_overrides(env_overrides, origin=origin))
