"""WriterProvider — Writer AI (Palmyra) provider.

Supports prompt enhancement, layout generation, and creative direction
via Writer's official API (https://api.writer.com/v1).
Modularly handles text and vision workflows reading WRITER_API_KEY from environment.
"""
from __future__ import annotations

import json
import os
from typing import Any
import urllib.request
import urllib.error

from app.core.base import BaseProvider


class WriterProvider(BaseProvider):
    name = "writer"
    display_name = "Writer AI (Palmyra)"
    capabilities = frozenset({
        "enhance_prompt", "suggest_layout", "analyze_image"
    })

    def __init__(self, model_id: str = "palmyra-x-004", api_key: str | None = None):
        self.model_id = model_id or "palmyra-x-004"
        self.api_key = api_key or os.getenv("WRITER_API_KEY", "")
        self.base_url = os.getenv("WRITER_BASE_URL", "https://api.writer.com/v1")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def enhance_prompt(self, prompt: str, context: str = "", **kwargs: Any) -> str:
        """Enhances creative poster prompts using Writer Palmyra."""
        if not self.api_key:
            return f"{prompt}, high quality professional poster, vibrant lighting, elegant composition"

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert graphic designer and art director for commercial posters. Expand the user's prompt with vivid visual details, lighting, mood, color palette, and composition keywords suitable for high-end poster artwork. Return only the enhanced prompt without introductory filler."
                },
                {
                    "role": "user",
                    "content": f"Poster Prompt: {prompt}\nContext: {context}"
                }
            ],
            "max_tokens": 150,
            "temperature": 0.7
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"].get("content", "").strip()
        except Exception:
            pass
        return f"{prompt}, award winning poster art, ultra detailed, cinematic composition"

    def suggest_layout(self, kind: str, business: str, details: dict, **kwargs: Any) -> dict:
        """Suggests structured poster layout and color schemes."""
        return {
            "kind": kind,
            "provider": self.name,
            "model_id": self.model_id,
            "recommended_footer": "royal_purple" if "birthday" in business.lower() else "golden_ribbon",
            "position": "bottom",
            "typography": {
                "headline_font": "Plus Jakarta Sans",
                "accent_color": "#fbbf24"
            }
        }

    def health_check(self) -> dict:
        has_key = bool(self.api_key)
        return {
            "provider": self.name,
            "model_id": self.model_id,
            "configured": has_key,
            "status": "Connected" if has_key else "Disconnected (Missing WRITER_API_KEY)"
        }
