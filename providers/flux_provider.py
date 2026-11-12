"""FluxProvider — Black Forest Labs FLUX adapter (drop-in, config-selected).

Implements BaseProvider without touching any other file. Register it in
config.yaml like:

  flux:
    class: providers.flux_provider.FluxProvider
    model_id: flux-pro-1.1
    api_key_env: FLUX_API_KEY
    enabled: true

Verified against the official BFL docs (https://docs.bfl.ai):
  * Auth: request header `x-key: <API KEY>`
  * Generation: POST https://api.bfl.ai/v1/<endpoint>  (e.g. flux-pro-1.1)
      body: {"prompt": str, "width": int, "height": int}
      response: {"id": "...", "polling_url": "https://..."}   (async task)
  * Polling: GET <polling_url> (header x-key) until status == "Ready"
      result: {"status": "Ready", "result": {"sample": "<signed image url>"}}
  * Editing: POST https://api.bfl.ai/v1/flux-kontext-pro with
      {"prompt": str, "input_image": <base64 image string>}
      (Kontext = FLUX's image-editing model, image+text -> image)
  * Text-only features (analyze / layout JSON / prompt enhancement) are NOT
    declared in capabilities — the registry rejects them with a clear message
    instead of pretending support (spec rule: never fake capabilities).

Free-tier reality (spec rule 22): BFL API is credit-based, not free-tier.
The provider reports that honestly in health_check().
"""
from __future__ import annotations

import time
from typing import Any

from app.core.base import BaseProvider

API_BASE = "https://api.bfl.ai"
DEFAULT_GENERATE_ENDPOINT = "flux-pro-1.1"
DEFAULT_EDIT_ENDPOINT = "flux-kontext-pro"
POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 120.0


class FluxProvider(BaseProvider):
    name = "flux"
    display_name = "FLUX (Black Forest Labs)"
    capabilities = frozenset({"generate_image", "edit_image"})

    def __init__(self, model_id: str = DEFAULT_GENERATE_ENDPOINT,
                 api_key: str = "",
                 generate_endpoint: str = DEFAULT_GENERATE_ENDPOINT,
                 edit_endpoint: str = DEFAULT_EDIT_ENDPOINT):
        self.model_id = model_id
        self.api_key = api_key
        self.generate_endpoint = generate_endpoint
        self.edit_endpoint = edit_endpoint

    # ------------------------------------------------------------- internals
    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "FLUX_API_KEY is not set. Add it to .env or use the 'mock' "
                "provider for offline runs.")
        return {"x-key": self.api_key,
                "Content-Type": "application/json"}

    def _submit(self, endpoint: str, payload: dict) -> str:
        """Submit an async task, return its id/polling URL."""
        import httpx
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{API_BASE}/v1/{endpoint}",
                               headers=self._headers(), json=payload)
            resp.raise_for_status()
            body = resp.json()
        task_id = body.get("id")
        if not task_id:
            raise RuntimeError(f"BFL task submission failed: {body}")
        return body.get("polling_url") or f"{API_BASE}/v1/get_result?id={task_id}"

    def _poll_and_download(self, polling_url: str) -> bytes:
        """Poll until Ready, then download the signed sample URL."""
        import httpx
        deadline = time.time() + POLL_TIMEOUT_S
        with httpx.Client(timeout=30.0) as client:
            while time.time() < deadline:
                resp = client.get(polling_url, headers=self._headers())
                resp.raise_for_status()
                body = resp.json()
                status = body.get("status")
                if status == "Ready":
                    sample_url = (body.get("result") or {}).get("sample")
                    if not sample_url:
                        raise RuntimeError(f"BFL Ready without sample: {body}")
                    image = client.get(sample_url)
                    image.raise_for_status()
                    return image.content
                if status in ("Error", "Request Moderated",
                              "Content Moderated"):
                    raise RuntimeError(f"BFL task failed: status={status}")
                time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"BFL task did not finish in {POLL_TIMEOUT_S:.0f}s")

    # --------------------------------------------------------------- features
    def generate_image(self, prompt: str, *, width: int = 1024,
                       height: int = 1024, **kwargs: Any) -> bytes:
        polling_url = self._submit(self.generate_endpoint, {
            "prompt": prompt,
            "width": int(width),
            "height": int(height),
        })
        return self._poll_and_download(polling_url)

    def edit_image(self, image_bytes: bytes, prompt: str, *,
                   mime_type: str = "image/png", **kwargs: Any) -> bytes:
        import base64
        polling_url = self._submit(self.edit_endpoint, {
            "prompt": prompt,
            "input_image": base64.b64encode(image_bytes).decode("utf-8"),
        })
        return self._poll_and_download(polling_url)

    # analyze_image / suggest_layout / enhance_prompt intentionally NOT
    # implemented — capabilities excludes them, the registry blocks them.

    def health_check(self) -> dict:
        return {"provider": self.name, "model_id": self.model_id,
                "configured": bool(self.api_key),
                "billing": "paid", "status": "PAID",
                "note": "Paid API only - excluded from free-tier testing"}
