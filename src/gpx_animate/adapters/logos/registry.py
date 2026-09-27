"""Loading logo images.

Today this is just "read a PNG path". M5 replaces it with the registry that
``logos/registry.yaml`` describes, mapping names to files and to the start, end
and moving-marker placements. The port is already in place for that.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np


logger = logging.getLogger(__name__)


class PngLogoLoader:
    """Reads a logo from a filesystem path.

    Attributes:
        registry_dir: Directory that names in the registry would resolve
            against. Unused until M5 adds the registry, but recorded so the
            resolution rule is in one place.
    """

    def __init__(self, registry_dir: Path | None = None) -> None:
        """Bind the loader to a registry directory.

        Args:
            registry_dir: Where ``logos/registry.yaml`` will live.
        """
        self.registry_dir = registry_dir

    def load(self, source: str) -> np.ndarray:
        """Read a logo image.

        Args:
            source: Path to an image file.

        Returns:
            The image as a float array, ready for ``imshow``.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = Path(source)
        logger.debug("Loading logo %s", path)
        return mpimg.imread(path)
