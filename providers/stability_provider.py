"""Stability AI provider for image generation and editing using promotional/trial credits.

Implements BaseProvider with:
  * generate_image via /v1/generation/{model_id}/text-to-image
  * edit_image via /v1/generation/{model_id}/image-to-image
  * Live credit / remaining quota checking via /v1/user/balance
  * Strict stop when credits <= 0 (never upgrades to paid).
"""
from __future__ import annotations

import base64
import os
from typing import Any

from app.core.base import BaseProvider
from providers._util import http_error, to_png

API_BASE = "https://api.stability.ai"
DEFAULT_MODEL_ID = "stable-diffusion-xl-1024-v1-0"


class StabilityProvider(BaseProvider):
    name = "stability"
    display_name = "Stability AI (SDXL)"
    capabilities = frozenset({"generate_image", "edit_image"})

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, api_key: str = "", **_: Any):
        self.model_id = model_id
        self.api_key = api_key or os.environ.get("STABILITY_API_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def get_remaining_credits(self) -> float | None:
        """Query live remaining credits from Stability balance endpoint."""
        import httpx
        if not self.configured:
            return None
        try:
            with httpx.Client(timeout=15.0) as c:
                r = c.get(f"{API_BASE}/v1/user/balance", headers={"Authorization": f"Bearer {self.api_key}"})
                if r.status_code == 200:
                    return float(r.json().get("credits", 0.0))
        except Exception:
            pass
        return None

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024, **kw: Any) -> bytes:
        import httpx
        if not self.configured:
            raise RuntimeError("STABILITY_API_KEY is not set in .env")

        # Verify free/trial quota remains before sending request
        credits = self.get_remaining_credits()
        if credits is not None and credits <= 0:
            raise RuntimeError("Stability AI promotional trial credits exhausted. Stopped per free-tier only rule.")

        # Stability SDXL v1.0 requires standard dimensions (multiples of 64 or 1024x1024)
        w = max(512, (int(width) // 64) * 64)
        h = max(512, (int(height) // 64) * 64)
        import random
        seed = kw.get("seed") if kw.get("seed") is not None else random.randint(1, 4294967295)

        url = f"{API_BASE}/v1/generation/{self.model_id}/text-to-image"
        body = {
            "text_prompts": [{"text": prompt, "weight": 1.0}],
            "cfg_scale": 7,
            "height": h,
            "width": w,
            "samples": 1,
            "steps": 30,
            "seed": seed,
        }
        with httpx.Client(timeout=120.0) as c:
            r = c.post(url, headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                       json=body)

        if r.status_code != 200:
            raise http_error(r)

        data = r.json()
        artifacts = data.get("artifacts", [])
        if not artifacts or not artifacts[0].get("base64"):
            raise RuntimeError("Stability AI returned no image artifacts")

        raw = base64.b64decode(artifacts[0]["base64"])
        return to_png(raw)

    def edit_image(self, image_bytes: bytes, prompt: str, *, mime_type: str = "image/png", **kw: Any) -> bytes:
        import httpx
        if not self.configured:
            raise RuntimeError("STABILITY_API_KEY is not set in .env")

        credits = self.get_remaining_credits()
        if credits is not None and credits <= 0:
            raise RuntimeError("Stability AI promotional trial credits exhausted. Stopped per free-tier only rule.")

        url = f"{API_BASE}/v1/generation/{self.model_id}/image-to-image"
        files = {"init_image": ("input.png", image_bytes, mime_type or "image/png")}
        data = {
            "text_prompts[0][text]": prompt,
            "text_prompts[0][weight]": "1.0",
            "image_strength": "0.35",
            "cfg_scale": "7",
            "samples": "1",
            "steps": "30",
        }
        with httpx.Client(timeout=120.0) as c:
            r = c.post(url, headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                       files=files, data=data)

        if r.status_code != 200:
            raise http_error(r)

        artifacts = r.json().get("artifacts", [])
        if not artifacts or not artifacts[0].get("base64"):
            raise RuntimeError("Stability AI returned no image artifacts for edit")

        raw = base64.b64decode(artifacts[0]["base64"])
        return to_png(raw)

    def health_check(self) -> dict:
        credits = self.get_remaining_credits() if self.configured else None
        return {
            "provider": self.name,
            "model_id": self.model_id,
            "configured": self.configured,
            "billing": "trial",
            "status": "TRIAL",
            "credits_remaining": credits,
            "note": "Promotional credits only; strictly stops when credits reach zero"
        }

