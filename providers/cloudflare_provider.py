"""Cloudflare Workers AI image models (needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID).

POST https://api.cloudflare.com/client/v4/accounts/<id>/ai/run/<model>. Request formats differ by model family:
  * flux-1-schnell: JSON {prompt, steps}; no size input, so output size is the model default.
  * flux-2-*: multipart form (prompt, width, height). UNVERIFIED here: confirm against the model page.
  * others (e.g. SDXL): JSON {prompt, width, height}; may return raw image bytes.
Free allowance is a shared daily neuron budget, not a per-model image count: set daily_limit in config.yaml.
"""
from __future__ import annotations

import base64
import os
from typing import Any

from app.core.base import BaseProvider
from providers._util import http_error, to_png


class CloudflareProvider(BaseProvider):
    name = "cloudflare"
    display_name = "Cloudflare Workers AI"
    capabilities = frozenset({"generate_image"})

    def __init__(self, model_id: str = "@cf/black-forest-labs/flux-1-schnell", api_key: str = "", **_: Any):
        self.model_id, self.api_key = model_id, api_key
        self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.account_id)

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024, **kw: Any) -> bytes:
        import httpx
        if not self.configured:
            raise RuntimeError("Set both CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in .env")
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.model_id}"
        hdr = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=120.0) as c:
            if "flux-1-schnell" in self.model_id:
                r = c.post(url, headers=hdr, json={"prompt": prompt, "steps": 4})
            elif "flux-2" in self.model_id:
                r = c.post(url, headers=hdr, files={"prompt": (None, prompt), "width": (None, str(int(width))),
                                                    "height": (None, str(int(height)))})
            else:
                r = c.post(url, headers=hdr, json={"prompt": prompt, "width": int(width), "height": int(height)})
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"Cloudflare authentication failed (HTTP {r.status_code}). "
                "Ensure your API Token has 'Workers AI: Read' or 'Workers AI: Edit' permission in Cloudflare dashboard."
            )
        if r.status_code == 429:
            raise RuntimeError("Cloudflare daily 10,000 neuron free limit reached. Stopped per free-tier only rule.")
        if r.status_code != 200:
            raise http_error(r)
        if r.headers.get("content-type", "").startswith("image/"):
            return to_png(r.content)
        body = r.json()
        img = (body.get("result") or body).get("image")
        if not img:
            raise RuntimeError(f"Cloudflare returned no image: {str(body)[:200]}")
        return to_png(base64.b64decode(img))

    def health_check(self) -> dict:
        return {"provider": self.name, "model_id": self.model_id, "configured": self.configured,
                "billing": "free daily allowance, then paid (verify in your dashboard)"}
