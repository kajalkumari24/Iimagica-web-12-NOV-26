"""Pytest suite — runs entirely on the mock provider, no API keys needed."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.core.base import GenerationResult
from app.core.colors import extract_brand_colors
from app.core.registry import (
    FeatureNotSupportedError,
    ProviderRegistry,
    UnknownProviderError,
)


def make_png(color=(200, 30, 30), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def reg(tmp_path) -> ProviderRegistry:
    """Registry restricted to the mock provider, isolated output dir."""
    r = ProviderRegistry()
    r.providers = {"mock": r.providers["mock"]}
    r.default_provider = "mock"
    r.features = {k: None for k in r.features}
    r.output_dir = str(tmp_path / "outputs")
    return r


# ---------------------------------------------------------------- interface
def test_mock_supports_all_features(reg):
    for feature in ("generate_image", "edit_image", "analyze_image",
                    "suggest_layout", "enhance_prompt"):
        result = reg.run(feature, {
            "generate_image": {"prompt": "p"},
            "edit_image": {"image_bytes": make_png(), "prompt": "p"},
            "analyze_image": {"image_bytes": make_png(), "question": "q"},
            "suggest_layout": {"kind": "frame", "business": "B", "details": {}},
            "enhance_prompt": {"prompt": "p"},
        }[feature])
        assert isinstance(result, GenerationResult)
        assert result.success, result.error


def test_switch_default_provider(reg):
    reg.providers["gemini"] = reg.providers["mock"]  # simulate second entry
    info = reg.switch_default("gemini")
    assert info == {"default_provider": "gemini",
                    "model_id": reg.providers["gemini"].model_id}


def test_switch_unknown_provider_fails(reg):
    with pytest.raises(UnknownProviderError):
        reg.switch_default("does_not_exist")


def test_feature_override_and_reset(reg):
    reg.providers["alt"] = reg.providers["mock"]
    reg.set_feature_provider("generate_image", "alt")
    assert reg.model_for("generate_image") == "mock-1"  # alt is same mock provider
    reg.set_feature_provider("generate_image", None)
    assert reg.features["generate_image"] is None


def test_unsupported_feature_rejected(reg):
    provider = reg.providers["mock"]
    provider.capabilities = frozenset({"generate_image"})  # narrow it
    try:
        with pytest.raises(FeatureNotSupportedError):
            reg._resolve_feature_provider("edit_image")
    finally:
        from app.core.base import BaseProvider as _B
        provider.capabilities = frozenset({
            "generate_image", "edit_image", "analyze_image",
            "suggest_layout", "enhance_prompt"})


def test_run_returns_normalized_failure(reg):
    broken = reg.providers["mock"]
    broken.generate_image = lambda **kw: (_ for _ in ()).throw(ValueError("boom"))
    result = reg.run("generate_image", {"prompt": "p"})
    assert result.success is False
    assert "boom" in result.error


# ---------------------------------------------------------------- endpoints
def test_api_models_and_switch():
    from fastapi.testclient import TestClient
    from app.api import app

    client = TestClient(app)
    data = client.get("/models").json()
    assert data["default_provider"] in data["providers"]
    assert "generate_image" in data["features"]

    resp = client.post("/switch", json={"provider": "mock"})
    assert resp.status_code == 200
    assert resp.json()["default_provider"] == "mock"

    bad = client.post("/switch", json={"provider": "nope"})
    assert bad.status_code == 400


def test_api_generate_endpoint():
    from fastapi.testclient import TestClient
    from app.api import app

    client = TestClient(app)
    client.post("/switch", json={"provider": "mock"})
    resp = client.post("/generate",
                       json={"prompt": "test", "width": 256, "height": 256})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] if "success" in body else body["image_base64"]
    assert base64.b64decode(body["image_base64"]).startswith(b"\x89PNG")


def test_api_layout_endpoint():
    from fastapi.testclient import TestClient
    from app.api import app

    client = TestClient(app)
    client.post("/switch", json={"provider": "mock"})
    resp = client.post("/layout", json={
        "kind": "footer", "business": "Sharma Sweets",
        "details": {"phone": "9876543210"}})
    assert resp.status_code == 200
    assert resp.json()["data"]["kind"] == "footer"


# ---------------------------------------------------------------- colors
def test_color_extraction():
    out = extract_brand_colors(make_png(color=(200, 30, 30)))
    assert out["colors"] and out["colors"][0] == "#C81E1E"
    assert out["method"] == "kmeans_numpy"
