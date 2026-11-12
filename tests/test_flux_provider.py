"""FLUX provider tests — mocked HTTP responses, no network, no API key.

Proves the drop-in promise: FluxProvider is selected purely through
config.yaml; no engine/API/test code knows it exists beyond BaseProvider.
"""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.core.base import BaseProvider
from app.core.registry import (
    FeatureNotSupportedError,
    ProviderRegistry,
)
from providers.flux_provider import FluxProvider

PNG_MAGIC = b"\x89PNG"


def make_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 100, 200)).save(buf, format="PNG")
    return buf.getvalue()


# ----------------------------------------------------------- fake HTTP layer
class FakeResponse:
    def __init__(self, body=None, content=b""):
        self._body = body
        self.content = content

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class FakeClient:
    """Scripted httpx.Client stand-in for the BFL task lifecycle."""
    script_posts = []
    script_gets = {}

    def __init__(self, *a, **kw):
        self.posts = 0
        self.gets = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        assert headers.get("x-key") == "test-key", "auth header must be x-key"
        assert "prompt" in json
        self.last_post_url = url
        return FakeResponse(body={"id": "task-123",
                                  "polling_url": "https://api.bfl.ai/v1/get_result?id=task-123"})

    def get(self, url, headers=None):
        if "get_result" in url:
            return FakeResponse(body={"status": "Ready",
                                      "result": {"sample": "https://cdn.example/sample.png"}})
        return FakeResponse(content=make_png())  # sample image download


@pytest.fixture()
def mock_http(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)


# ---------------------------------------------------------------- adapter
def test_flux_generate_with_mocked_http(mock_http):
    provider = FluxProvider(model_id="flux-pro-1.1", api_key="test-key")
    out = provider.generate_image("Diwali poster background")
    assert out.startswith(PNG_MAGIC)


def test_flux_edit_with_mocked_http(mock_http):
    provider = FluxProvider(model_id="flux-pro-1.1", api_key="test-key")
    out = provider.edit_image(make_png(), "replace background with gold")
    assert out.startswith(PNG_MAGIC)


def test_flux_does_not_fake_text_capabilities():
    provider = FluxProvider(api_key="test-key")
    assert not provider.supports("suggest_layout")
    assert not provider.supports("analyze_image")
    assert not provider.supports("enhance_prompt")


def test_flux_health_reports_config_and_billing():
    info = FluxProvider(api_key="test-key").health_check()
    assert info["configured"] is True
    assert "credit-based" in info["billing"]


# ------------------------------------------------- config-only switching
def test_flux_selected_by_config_only(mock_http, tmp_path, monkeypatch):
    """Swap the default provider by writing config.yaml — zero code edits."""
    monkeypatch.setenv("FLUX_API_KEY", "test-key")
    config = tmp_path / "config.yaml"
    config.write_text("""
default_provider: flux
providers:
  gemini:
    class: providers.gemini_provider.GeminiProvider
    model_id: gemini-nano-banana-2.1
    api_key_env: GEMINI_API_KEY
    enabled: true
  flux:
    class: providers.flux_provider.FluxProvider
    model_id: flux-pro-1.1
    api_key_env: FLUX_API_KEY
    enabled: true
features:
  generate_image: null
  edit_image: null
  analyze_image: null
  suggest_layout: null
  enhance_prompt: null
output_dir: outputs
""")
    registry = ProviderRegistry(config_path=str(config))
    assert registry.model_for("generate_image") == "flux-pro-1.1"

    result = registry.run("generate_image", {"prompt": "p"})
    assert result.success, result.error
    assert result.provider == "flux"
    assert result.data.startswith(PNG_MAGIC)


def test_flux_unsupported_feature_rejected_by_registry(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("""
default_provider: flux
providers:
  flux:
    class: providers.flux_provider.FluxProvider
    model_id: flux-pro-1.1
    api_key_env: FLUX_API_KEY
    enabled: true
features:
  generate_image: null
  edit_image: null
  analyze_image: null
  suggest_layout: null
  enhance_prompt: null
output_dir: outputs
""")
    registry = ProviderRegistry(config_path=str(config))
    with pytest.raises(FeatureNotSupportedError):
        registry._resolve_feature_provider("suggest_layout")


def test_flux_is_a_base_provider_subclass():
    assert issubclass(FluxProvider, BaseProvider)
