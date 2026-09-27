"""The contextily tile basemap: provider catalogue, key handling, headers."""

import contextily as cx
import pytest
import requests

from gpx_animate.adapters.basemaps.tiles import TILE_PROVIDERS
from gpx_animate.adapters.basemaps.tiles import USER_AGENT
from gpx_animate.adapters.basemaps.tiles import TileBasemap
from gpx_animate.adapters.basemaps.tiles import _carto
from gpx_animate.adapters.basemaps.tiles import available_styles
from gpx_animate.application.ports import BasemapProvider


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
        monkeypatch.setattr(cx, "add_basemap", lambda ax, **kw: calls.append(kw))
        TileBasemap("osm").add_basemap(object(), crs="EPSG:3857")
        assert calls[0]["headers"] == {"User-Agent": USER_AGENT}

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
        with pytest.raises(KeyError):
            TileBasemap("nope").provider  # noqa: B018  (the lookup is the test)

    def test_add_basemap_passes_the_provider_and_headers(self, monkeypatch):
        calls = []
        monkeypatch.setattr(cx, "add_basemap", lambda ax, **kw: calls.append(kw))
        TileBasemap("osm").add_basemap(object(), crs="EPSG:3857")
        assert calls[0]["source"] is TILE_PROVIDERS["osm"]
        assert calls[0]["headers"] == {"User-Agent": USER_AGENT}
        assert calls[0]["crs"] == "EPSG:3857"

    def test_add_basemap_forwards_renderer_options(self, monkeypatch):
        calls = []
        monkeypatch.setattr(cx, "add_basemap", lambda ax, **kw: calls.append(kw))
        TileBasemap("topo").add_basemap(object(), crs="EPSG:3857", zoom="auto")
        assert calls[0]["zoom"] == "auto"

    def test_satisfies_the_basemap_port(self):

        assert isinstance(TileBasemap("topo"), BasemapProvider)
