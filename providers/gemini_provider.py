"""GeminiProvider - Google Gemini for image generation, editing and text tasks.

Image models (e.g. gemini-nano-banana-2.1, gemini-3.1-flash-image):
    generate_image  text (+ optional reference images) -> image
    edit_image      image + instruction -> image
    analyze_image / suggest_layout / enhance_prompt  (text answers)
Text models (any id without "image"/"banana", e.g. a Gemini Flash model):
    analyze_image / suggest_layout / enhance_prompt only (cheaper, text-only).

Use two config entries to split the work - no code change needed:
    providers:
      gemini:      { model_id: gemini-nano-banana-2.1, ... }   # images
      gemini_text: { model_id: <a Gemini text model>,  ... }   # text tasks
    features:
      analyze_image: gemini_text
      suggest_layout: gemini_text
      enhance_prompt: gemini_text

What changed vs the old version:
  * Real aspect ratio / resolution via image_config (not a hint in the prompt).
  * Fixed image decoding: the SDK returns raw bytes; base64 is also handled.
  * Interim "thought" images are skipped; the final image is returned.
  * Reference images (logo, sample poster) are sent for generation.
  * The universal "no text" instruction is gone (prompt_builder decides).
  * Text models run text-only; retries on transient errors; friendly errors.
The google-genai SDK is imported lazily so mock mode and tests need no SDK.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

from app.core.base import BaseProvider
from app.core.prompt_builder import build_edit_prompt, closest_aspect_ratio

DEFAULT_MODEL_ID = "gemini-nano-banana-2.1"
VALID_SIZES = ("1K", "2K", "4K")  # uppercase K is required by the API
_TRANSIENT = ("503", "500", "UNAVAILABLE", "INTERNAL", "DEADLINE", "timed out",
              "timeout", "temporarily")


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _looks_like_image(data: bytes) -> bool:
    return (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def _to_bytes(data: Any) -> bytes | None:
    """SDK gives raw bytes; REST/older paths give base64 text. Handle both."""
    if data is None:
        return None
    if isinstance(data, str):
        return base64.b64decode(data)
    data = bytes(data)
    if _looks_like_image(data):
        return data
    try:
        decoded = base64.b64decode(data, validate=True)
        if _looks_like_image(decoded):
            return decoded
    except Exception:  # noqa: BLE001
        pass
    return data


def _friendly_error(exc: Exception) -> RuntimeError:
    text = str(exc)
    low = text.lower()
    if "resource_exhausted" in low or "429" in text or "quota" in low:
        return RuntimeError(
            "Gemini quota/billing limit reached. Image models have no free API "
            "tier - enable billing on your key, or switch to the free "
            f"'flux'/'mock' provider. Details: {text[:200]}")
    if "api key" in low or "api_key_invalid" in low or "permission_denied" in low \
            or "403" in text or "401" in text:
        return RuntimeError(
            f"Gemini rejected the API key or its permissions. Details: {text[:200]}")
    if "not found" in low or "404" in text:
        return RuntimeError(
            "Gemini model not found. Check model_id in config.yaml against "
            f"https://ai.google.dev/gemini-api/docs/models . Details: {text[:200]}")
    return RuntimeError(text)


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini (Nano Banana)"
    capabilities = frozenset({
        "generate_image", "edit_image", "analyze_image",
        "suggest_layout", "enhance_prompt",
    })

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, api_key: str = "",
                 max_retries: int = 2):
        self.model_id = model_id
        self.api_key = api_key
        self.max_retries = max_retries
        self._client = None
        self.is_image_model = any(t in model_id.lower() for t in ("image", "banana"))
        if not self.is_image_model:  # text model: no image output
            self.capabilities = frozenset(
                {"analyze_image", "suggest_layout", "enhance_prompt"})

    # ------------------------------------------------------------- internals
    def _get_client(self):
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to .env or use the "
                "'mock' provider for offline runs.")
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "google-genai is not installed: pip install google-genai"
                ) from exc
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _call(self, parts: list[dict], image_config: dict | None = None):
        """One model call with retries. image_config only for image models."""
        client = self._get_client()
        config: dict = {"response_modalities":
                        ["TEXT", "IMAGE"] if self.is_image_model else ["TEXT"]}
        if image_config and self.is_image_model:
            config["image_config"] = image_config
        attempt = 0
        while True:
            try:
                return client.models.generate_content(
                    model=self.model_id,
                    contents=[{"role": "user", "parts": parts}],
                    config=config)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                # model/API rejected image_config -> retry once without it
                if "image_config" in config and any(
                        k in msg.lower() for k in
                        ("image_config", "image_size", "aspect_ratio", "imageconfig")):
                    config.pop("image_config")
                    continue
                if attempt < self.max_retries and any(t in msg for t in _TRANSIENT):
                    attempt += 1
                    time.sleep(1.5 * attempt)
                    continue
                raise _friendly_error(exc) from exc

    @staticmethod
    def _image_part(image_bytes: bytes, mime_type: str | None = None) -> dict:
        return {"inline_data": {"mime_type": mime_type or _sniff_mime(image_bytes),
                                "data": image_bytes}}

    @staticmethod
    def _extract_image(response: Any) -> bytes | None:
        """Final image of the response; interim 'thought' images are skipped."""
        final: bytes | None = None
        fallback: bytes | None = None
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                raw = _to_bytes(getattr(inline, "data", None)) if inline else None
                if not raw:
                    continue
                if getattr(part, "thought", False):
                    fallback = raw
                else:
                    final = raw
        return final or fallback

    @staticmethod
    def _extract_text(response: Any) -> str:
        chunks = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None) and not getattr(part, "thought", False):
                    chunks.append(part.text)
        if chunks:
            return "\n".join(chunks)
        try:
            return response.text or ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = re.sub(r"```(?:json)?", "", text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"Model returned non-JSON layout: {text[:200]}")
        return json.loads(match.group(0))

    def _need_image_model(self, feature: str) -> None:
        if not self.is_image_model:
            raise RuntimeError(
                f"'{self.model_id}' is a text model and cannot {feature}. "
                "Use an image model such as gemini-nano-banana-2.1.")

    @staticmethod
    def _norm_size(size: Any) -> str:
        size = str(size or "1K").upper().replace("PX", "")
        return size if size in VALID_SIZES else "1K"

    # --------------------------------------------------------------- features
    def generate_image(self, prompt: str, width: int = 1024,
                       height: int = 1024, **kwargs: Any) -> bytes:
        """kwargs: image_size ('1K'|'2K'|'4K'), reference_images (list[bytes])."""
        self._need_image_model("generate images")
        parts: list[dict] = [{"text": prompt}]
        for ref in (kwargs.get("reference_images") or [])[:10]:
            parts.append(self._image_part(ref))
        cfg = {"aspect_ratio": closest_aspect_ratio(width, height),
               "image_size": self._norm_size(kwargs.get("image_size"))}
        response = self._call(parts, image_config=cfg)
        image = self._extract_image(response)
        if image is None:
            raise RuntimeError(
                "Model returned no image (it may have refused the prompt). "
                f"Model said: {self._extract_text(response)[:200]!r}")
        return image

    def edit_image(self, image_bytes: bytes, prompt: str,
                   mime_type: str = "image/png", **kwargs: Any) -> bytes:
        """kwargs: reference_images (list[bytes]), image_size, aspect_ratio."""
        self._need_image_model("edit images")
        instruction = prompt if prompt.startswith("Edit the supplied") \
            else build_edit_prompt(prompt)
        parts: list[dict] = [{"text": instruction},
                             self._image_part(image_bytes, mime_type)]
        for ref in (kwargs.get("reference_images") or [])[:9]:
            parts.append(self._image_part(ref))
        cfg: dict = {"image_size": self._norm_size(kwargs.get("image_size"))}
        if kwargs.get("aspect_ratio"):
            cfg["aspect_ratio"] = kwargs["aspect_ratio"]
        response = self._call(parts, image_config=cfg)
        image = self._extract_image(response)
        if image is None:
            raise RuntimeError("Model returned no image for the edit request")
        return image

    def analyze_image(self, image_bytes: bytes, question: str,
                      mime_type: str = "image/png", **kwargs: Any) -> str:
        response = self._call([{"text": question},
                               self._image_part(image_bytes, mime_type)])
        return self._extract_text(response)

    def suggest_layout(self, kind: str, business: str, details: dict,
                       **kwargs: Any) -> dict:
        base = (f"Business: {business}. Context (style, poster idea, palette): "
                f"{json.dumps(details, ensure_ascii=False)}. ")
        if kind == "frame":
            instruction = (
                "You are a senior graphic designer choosing a border/frame for a "
                "promotional poster. " + base +
                'Return ONLY JSON: {"shape": one of [rectangle, rounded, double, '
                'floating], "border_thickness": int px (relative to a 1000px '
                'poster), "padding": int px, "reason": short string}')
        else:
            instruction = (
                "You are a senior graphic designer choosing a footer design for a "
                "promotional poster. Pick a distinctive style that suits the "
                "occasion and palette; do not always pick a plain rectangle. "
                + base +
                'Return ONLY JSON: {"shape": one of [curved, wave, diagonal, '
                'double, floating, layered, rounded, rectangle], '
                '"height_ratio": number between 0.10 and 0.20 (share of poster '
                'height), "reason": short string}')
        text = self._extract_text(self._call([{"text": instruction}]))
        return self._parse_json(text)

    def enhance_prompt(self, prompt: str, context: str = "",
                       **kwargs: Any) -> str:
        response = self._call([{"text":
            "Rewrite this poster prompt as a richer prompt for an image model: "
            "add composition, lighting, textures, color and mood. Keep EVERY "
            "detail the user specified (subjects, names, numbers, colors, text) "
            f"unchanged. Context: {context}. Prompt: {prompt}. "
            "Return only the improved prompt."}])
        return self._extract_text(response).strip() or prompt

    def health_check(self) -> dict:
        return {
            "provider": self.name,
            "model_id": self.model_id,
            "configured": bool(self.api_key),
            "kind": "image" if self.is_image_model else "text",
            "billing": "paid" if self.is_image_model else "free_tier",
            "status": "PAID" if self.is_image_model else "FREE",
            "note": "Image models require paid billing; text models have free tier"
        }
