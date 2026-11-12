"""MockProvider — offline stub provider.

Proves the swap works: flip `default_provider: mock` in config.yaml and the
whole platform runs with zero API keys. Also used by the pytest suite.
"""
from __future__ import annotations

import io
import json
from typing import Any

from app.core.base import BaseProvider

# 1x1 red PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8cfc00000030101"
    "00183d24c10000000049454e44ae426082"
)


class MockProvider(BaseProvider):
    name = "mock"
    display_name = "Mock Provider (offline)"
    capabilities = frozenset({
        "generate_image", "edit_image", "analyze_image",
        "suggest_layout", "enhance_prompt",
    })

    def __init__(self, model_id: str = "mock-1", api_key: str = ""):
        self.model_id = model_id

    def generate_image(self, prompt: str, width: int = 1024,
                       height: int = 1024, **kwargs: Any) -> bytes:
        return _PNG

    def edit_image(self, image_bytes: bytes, prompt: str,
                   mime_type: str = "image/png", **kwargs: Any) -> bytes:
        return _PNG

    def analyze_image(self, image_bytes: bytes, question: str,
                      mime_type: str = "image/png", **kwargs: Any) -> str:
        return f"[mock analysis] {question}"

    def suggest_layout(self, kind: str, business: str, details: dict,
                       **kwargs: Any) -> dict:
        if kind == "frame":
            return {"kind": "frame", "shape": "rounded", "mock": True,
                    "border_thickness": 12, "logo_position": "top_center"}
        return {"kind": "footer", "shape": "rectangle", "mock": True,
                "slots": ["logo", "name", "phone", "qr"]}

    def enhance_prompt(self, prompt: str, context: str = "",
                       **kwargs: Any) -> str:
        return f"[mock-enhanced] {prompt}"

    def health_check(self) -> dict:
        return {"provider": self.name, "model_id": self.model_id,
                "configured": True}
