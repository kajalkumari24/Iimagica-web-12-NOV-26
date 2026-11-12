"""Pollinations image API. GET <base>/<url-encoded prompt>?width&height&model. The key is optional.

Access terms change, so this is UNVERIFIED until the live test passes. Override the base with POLLINATIONS_BASE.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from app.core.base import BaseProvider
from providers._util import http_error, to_png


class PollinationsProvider(BaseProvider):
    name = "pollinations"
    display_name = "Pollinations"
    capabilities = frozenset({"generate_image"})

    def __init__(self, model_id: str = "flux", api_key: str = "", **_: Any):
        self.model_id, self.api_key = model_id, api_key
        default_base = "https://gen.pollinations.ai/image" if api_key else "https://image.pollinations.ai/prompt"
        self.base = os.environ.get("POLLINATIONS_BASE", default_base)

    configured = True  # works without a key; terms may require one

    def generate_image(self, prompt: str, *, width: int = 1024, height: int = 1024, **kw: Any) -> bytes:
        import httpx
        import random
        hdr = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        seed = kw.get("seed")
        if seed is None:
            seed = random.randint(1, 2147483647)
        params = {
            "width": int(width),
            "height": int(height),
            "model": self.model_id,
            "seed": seed,
            "nologo": "true"
        }
        with httpx.Client(timeout=180.0, follow_redirects=True) as c:
            r = c.get(f"{self.base}/{quote(prompt, safe='')}", headers=hdr, params=params)
        if r.status_code != 200:
            raise http_error(r)
        return to_png(r.content)

    def health_check(self) -> dict:
        return {"provider": self.name, "model_id": self.model_id, "configured": True,
                "billing": "free", "status": "FREE", "quota": "unlimited with pollen key / free access"}
