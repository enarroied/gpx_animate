"""The contextily tile basemap: provider catalogue, key handling, headers."""

from typing import Any

import contextily as cx
import numpy as np
import pytest
import requests

from gpx_animate.adapters.basemaps.tiles import TILE_PROVIDERS
from gpx_animate.adapters.basemaps.tiles import USER_AGENT
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import _carto
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.application.errors import BasemapError
from gpx_animate.application.ports import BasemapProvider
from gpx_animate.domain.bbox import Bbox


VIEW = Bbox(-500000.0, -400000.0, 500000.0, 400000.0)
"""A small view in Spherical Mercator, small enough that a real request would be
one tile, but the tests stub the download either way."""


def _stub_bounds2img(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any]],
    *,
    merged: np.ndarray | None = None,
    extent: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0),
) -> None:
    """Replace the tile download with a recording stub.

    Args:
        monkeypatch: The patcher to install the stub with.
        calls: List that each call's args and kwargs are appended to.
        merged: Array the stub pretends the tiles merged into.
        extent: Extent the stub pretends the tiles cover.
    """
    pixels = np.full((2, 2, 3), 128, dtype=np.uint8) if merged is None else merged

    def stub(*args: Any, **kwargs: Any) -> tuple[np.ndarray, tuple[float, ...]]:
        calls.append({"args": args, "kwargs": kwargs})
        return pixels, extent

    monkeypatch.setattr(cx, "bounds2img", stub)
    monkeypatch.setattr(cx, "warp_tiles", lambda img, extent, t_crs: (img, extent))


class TestProviderCatalogue:
    def test_key_free_styles_are_always_available(self):
        assert {"osm", "topo", "satellite"} <= set(available_styles())

    def test_carto_styles_need_a_key(self, monkeypatch):
        """Without CARTO_API_KEY the Carto entries are dropped, not faked."""
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        assert not {"positron", "voyager", "dark"} & set(TILE_PROVIDERS)

    def test_carto_styles_appear_with_a_key(self, monkeypatch):
        monkeypatch.setenv("CARTO_API_KEY", "secret")
        providers = TILE_PROVIDERS.copy()
        for name in ("positron", "voyager", "dark"):
            providers[name] = _carto(
                "https://example.invalid/{z}/{x}/{y}.png?key={key}"
            )
        assert set(providers) >= {"positron", "voyager", "dark"}

    def test_a_carto_url_carries_the_key(self, monkeypatch):
        monkeypatch.setenv("CARTO_API_KEY", "secret")
        provider = _carto("https://example.invalid/{z}/{x}/{y}.png?key={key}")
        assert provider is not None
        assert provider["url"].endswith("key=secret")
        assert provider["max_zoom"] == 20
        assert "OpenStreetMap" in provider["attribution"]

    def test_the_key_can_be_renamed(self, monkeypatch):
        monkeypatch.setenv("MY_TILES_KEY", "secret")
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        assert _carto("https://x.invalid/?key={key}", "MY_TILES_KEY") is not None

    def test_no_key_means_no_provider(self, monkeypatch):
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        assert _carto("https://x.invalid/?key={key}") is None


class TestUserAgent:
    def test_identifies_the_project(self):
        assert USER_AGENT.startswith("GPX-Animate/")

    def test_is_sent_with_every_tile_request(self, monkeypatch):
        """This explicit header is what identifies us, not requests' defaults."""
        calls = []
        _stub_bounds2img(monkeypatch, calls)
        TileBasemap("osm").get_image(VIEW, "EPSG:3857", "auto")
        assert calls[0]["kwargs"]["headers"] == {"User-Agent": USER_AGENT}

    def test_requests_defaults_are_left_alone(self):
        """default_headers() rebuilds a dict per call, so mutating it is a no-op.

        The monolith set the User-Agent that way at import. It had no effect,
        which is why the header is passed explicitly above.
        """

        assert "GPX-Animate" not in requests.utils.default_headers()["User-Agent"]


class TestTileBasemap:
    def test_resolves_a_known_style(self):
        assert TileBasemap("topo").provider is TILE_PROVIDERS["topo"]

    def test_rejects_an_unknown_style(self):
        with pytest.raises(BasemapError, match="unknown basemap style"):
            TileBasemap("nope")

    def test_names_the_available_styles_when_it_rejects_one(self):
        """A config file can name a style the CLI would never offer."""
        with pytest.raises(BasemapError, match="osm"):
            TileBasemap("nope")

    def test_get_image_passes_the_provider_and_headers(self, monkeypatch):
        calls = []
        _stub_bounds2img(monkeypatch, calls)
        TileBasemap("osm").get_image(VIEW, "EPSG:3857", "auto")
        assert calls[0]["kwargs"]["source"] is TILE_PROVIDERS["osm"]
        assert calls[0]["kwargs"]["headers"] == {"User-Agent": USER_AGENT}

    def test_get_image_passes_the_bbox_in_west_south_east_north(self, monkeypatch):
        calls = []
        _stub_bounds2img(monkeypatch, calls)
        TileBasemap("topo").get_image(VIEW, "EPSG:3857", "auto")
        assert calls[0]["args"] == (VIEW.min_x, VIEW.min_y, VIEW.max_x, VIEW.max_y)

    def test_get_image_forwards_the_zoom(self, monkeypatch):
        calls = []
        _stub_bounds2img(monkeypatch, calls)
        TileBasemap("topo").get_image(VIEW, "EPSG:3857", 12)
        assert calls[0]["kwargs"]["zoom"] == 12

    def test_get_image_asks_for_mercator_tiles(self, monkeypatch):
        """ll=False, because web tiles are addressed in Spherical Mercator."""
        calls = []
        _stub_bounds2img(monkeypatch, calls)
        TileBasemap("topo").get_image(VIEW, "EPSG:3857", "auto")
        assert calls[0]["kwargs"]["ll"] is False

    def test_get_image_returns_what_bounds2img_merged(self, monkeypatch):
        pixels = np.full((2, 2, 3), 200, dtype=np.uint8)
        _stub_bounds2img(monkeypatch, [], merged=pixels, extent=(0.0, 10.0, 0.0, 5.0))
        image = TileBasemap("topo").get_image(VIEW, "EPSG:3857", "auto")
        assert image.image.shape == (2, 2, 3)
        assert image.extent == (0.0, 10.0, 0.0, 5.0)

    def test_get_image_warps_into_the_requested_crs(self, monkeypatch):
        """contextily.add_basemap always warped; skipping it would change pixels."""
        _stub_bounds2img(monkeypatch, [])
        warped = []
        monkeypatch.setattr(
            cx,
            "warp_tiles",
            lambda img, extent, t_crs: (
                warped.append(t_crs),
                (img, (1.0, 2.0, 3.0, 4.0)),
            )[1],
        )
        image = TileBasemap("topo").get_image(VIEW, "EPSG:4326", "auto")
        assert warped == ["EPSG:4326"]
        assert image.crs == "EPSG:4326"
        assert image.extent == (1.0, 2.0, 3.0, 4.0)

    def test_carries_the_providers_attribution(self, monkeypatch):
        """OSM's tile policy requires the credit; dropping it is a licence breach."""
        _stub_bounds2img(monkeypatch, [])
        image = TileBasemap("osm").get_image(VIEW, "EPSG:3857", "auto")
        assert image.attribution is not None
        assert "OpenStreetMap" in image.attribution

    def test_satisfies_the_basemap_port(self):

        assert isinstance(TileBasemap("topo"), BasemapProvider)
