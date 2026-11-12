"""Hugging Face Inference Providers, text-to-image (needs HF_TOKEN).

Default route: POST https://router.huggingface.co/hf-inference/models/<model> with {"inputs", "parameters"}.
Override with HF_INFERENCE_BASE if your account uses a different provider route. UNVERIFIED until you run the
live test. Free accounts get only a small monthly credit, so set daily_limit and keep runs small.
"""
from __future__ import annotations

import os
from typing import Any

from app.core.base import BaseProvider
from providers._util import http_error, to_png


class HuggingFaceProvider(BaseProvider):
    name = "huggingface"
    display_name = "Hugging Face Inference Providers"
    capabilities = frozenset({"generate_image"})

    def __init__(self, model_id: str = "black-forest-labs/FLUX.1-schnell", api_key: str = "", **_: Any):
        self.model_id = model_id
        self.api_key = api_key or os.environ.get("HUGGINGFACE_API_KEY", "") or os.environ.get("HF_TOKEN", "")
        self.base = os.environ.get("HF_INFERENCE_BASE", "https://router.huggingface.co/hf-inference/models")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024, **kw: Any) -> bytes:
        import httpx
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY or HF_TOKEN is not set in .env")
        with httpx.Client(timeout=120.0) as c:
            r = c.post(f"{self.base}/{self.model_id}", headers={"Authorization": f"Bearer {self.api_key}", "Accept": "image/png"},
                       json={"inputs": prompt, "parameters": {"width": int(width), "height": int(height)}})
        if r.status_code == 410 or r.status_code == 400:
            raise RuntimeError(f"Hugging Face serverless image generation is no longer available on free tier for {self.model_id} (HTTP {r.status_code}).")
        if r.status_code != 200:
            raise http_error(r)
        return to_png(r.content)

    def health_check(self) -> dict:
        return {"provider": self.name, "model_id": self.model_id, "configured": self.configured,
                "billing": "paid", "status": "PAID", "note": "No free serverless image model available without paid endpoints"}
