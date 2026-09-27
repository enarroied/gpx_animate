"""The GUI stub, so the M8 entry point exists and says so."""

import pytest

from gpx_animate.adapters.gui.main import main


def test_it_refuses_to_run_and_points_at_the_cli():
    """A stub that silently did nothing would be worse than none at all."""
    with pytest.raises(NotImplementedError, match="M8"):
        main()


def test_the_message_names_the_cli_to_use_instead():
    with pytest.raises(NotImplementedError, match="gpx-animate"):
        main()
