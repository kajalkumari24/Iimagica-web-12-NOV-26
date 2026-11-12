"""GeminiProvider tests with a fake client - no API key, no network."""
from __future__ import annotations

import base64
import io
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from providers.gemini_provider import GeminiProvider


def png(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def part(data=None, text=None, thought=False):
    inline = NS(data=data) if data is not None else None
    return NS(inline_data=inline, text=text, thought=thought)


def response(*parts):
    return NS(candidates=[NS(content=NS(parts=list(parts)))], text=None)


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.models = NS(generate_content=self._gen)

    def _gen(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def provider(model="gemini-nano-banana-2.1", replies=()):
    p = GeminiProvider(model_id=model, api_key="k", max_retries=1)
    p._client = FakeClient(replies)
    return p


def test_raw_bytes_from_sdk_are_returned_unchanged():
    img = png()
    p = provider(replies=[response(part(data=img))])
    assert p.generate_image("poster", 1080, 1350) == img


def test_base64_text_is_decoded():
    img = png()
    p = provider(replies=[response(part(data=base64.b64encode(img).decode()))])
    assert p.generate_image("poster") == img


def test_thought_images_are_skipped():
    final, thought = png((1, 2, 3)), png((9, 9, 9))
    p = provider(replies=[response(part(data=final), part(data=thought, thought=True))])
    assert p.generate_image("poster") == final


def test_aspect_ratio_and_size_sent_via_image_config():
    p = provider(replies=[response(part(data=png()))])
    p.generate_image("poster", 1080, 1350, image_size="2k")
    cfg = p._client.calls[0]["config"]
    assert cfg["image_config"] == {"aspect_ratio": "4:5", "image_size": "2K"}
    assert cfg["response_modalities"] == ["TEXT", "IMAGE"]


def test_prompt_is_not_polluted_with_no_text_rule():
    p = provider(replies=[response(part(data=png()))])
    p.generate_image("Diwali poster with headline", 1024, 1024)
    sent = p._client.calls[0]["contents"][0]["parts"][0]["text"]
    assert sent == "Diwali poster with headline"


def test_reference_images_are_sent():
    p = provider(replies=[response(part(data=png()))])
    p.generate_image("poster", reference_images=[png(), png()])
    parts = p._client.calls[0]["contents"][0]["parts"]
    assert len(parts) == 3 and parts[1]["inline_data"]["mime_type"] == "image/png"


def test_retries_without_image_config_if_rejected():
    p = provider(replies=[RuntimeError("Unknown field image_size"),
                          response(part(data=png()))])
    assert p.generate_image("poster")
    assert "image_config" not in p._client.calls[1]["config"]


def test_transient_error_is_retried(monkeypatch):
    monkeypatch.setattr("providers.gemini_provider.time.sleep", lambda s: None)
    p = provider(replies=[RuntimeError("503 UNAVAILABLE"), response(part(data=png()))])
    assert p.generate_image("poster")


def test_quota_error_is_friendly():
    p = provider(replies=[RuntimeError("429 RESOURCE_EXHAUSTED")])
    with pytest.raises(RuntimeError, match="billing"):
        p.generate_image("poster")


def test_no_image_returns_clear_error():
    p = provider(replies=[response(part(text="I cannot do that"))])
    with pytest.raises(RuntimeError, match="no image"):
        p.generate_image("poster")


def test_edit_wraps_instruction_and_keeps_unrelated_parts():
    p = provider(replies=[response(part(data=png()))])
    p.edit_image(png(), "make the background darker")
    parts = p._client.calls[0]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Edit the supplied image")
    assert "Preserve" in parts[0]["text"] and "inline_data" in parts[1]


def test_text_model_is_text_only():
    p = provider(model="some-text-model", replies=[response(part(text='```json\n{"shape":"curved"}\n```'))])
    assert "generate_image" not in p.capabilities
    out = p.suggest_layout("footer", "Shop", {})
    assert out == {"shape": "curved"}
    assert p._client.calls[0]["config"]["response_modalities"] == ["TEXT"]
    with pytest.raises(RuntimeError, match="text model"):
        p.generate_image("x")


def test_missing_key_message():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider(api_key="").generate_image("x")
