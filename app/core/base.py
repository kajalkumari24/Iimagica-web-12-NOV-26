"""BaseProvider — the single interface every model must implement.

Every iimagica AI feature maps to exactly one method:
    generate_image  → poster background generation (text-to-image)
    edit_image      → poster editing / background replace / logo-safe edit
    analyze_image   → logo & image understanding
    suggest_layout  → frame OR footer design suggestion (JSON)
    enhance_prompt  → prompt enhancement

A provider may support any subset — `capabilities` declares what it can do and
the registry rejects unsupported features with a clear message. The engines and
the API never import a concrete provider; they only use this interface, which is
what makes model switching a configuration change instead of a code change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


FEATURES: tuple[str, ...] = (
    "generate_image",
    "edit_image",
    "analyze_image",
    "suggest_layout",
    "enhance_prompt",
)


@dataclass
class GenerationResult:
    """Normalized response — identical shape for every provider."""
    feature: str
    provider: str
    model_id: str
    success: bool
    data: Any = None          # image bytes (images) / dict (JSON) / str (text)
    mime_type: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class BaseProvider(ABC):
    """Common interface. Subclass this to add a new model in one file."""

    name: str = "base"
    display_name: str = "Base Provider"
    model_id: str = "unknown"
    capabilities: frozenset[str] = frozenset()

    # -- feature methods --
    # Implement only the ones you declare in `capabilities`. The rest stay
    # as concrete stubs so a provider covering a subset (e.g. FLUX: image
    # generation + editing only) can be instantiated without stubbing the
    # others; the registry never calls undeclared features anyway.

    def generate_image(self, prompt: str, width: int = 1024,
                       height: int = 1024, **kwargs: Any) -> bytes:
        """Text-to-image. Returns raw image bytes (PNG)."""
        raise NotImplementedError(
            f"{self.name} does not implement generate_image")

    def edit_image(self, image_bytes: bytes, prompt: str,
                   mime_type: str = "image/png", **kwargs: Any) -> bytes:
        """Image + text → image. Returns raw image bytes (PNG)."""
        raise NotImplementedError(
            f"{self.name} does not implement edit_image")

    def analyze_image(self, image_bytes: bytes, question: str,
                      mime_type: str = "image/png", **kwargs: Any) -> str:
        """Image understanding. Returns analysis text."""
        raise NotImplementedError(
            f"{self.name} does not implement analyze_image")

    def suggest_layout(self, kind: str, business: str, details: dict,
                       **kwargs: Any) -> dict:
        """Frame/footer design suggestion. Returns layout JSON (dict)."""
        raise NotImplementedError(
            f"{self.name} does not implement suggest_layout")

    def enhance_prompt(self, prompt: str, context: str = "",
                       **kwargs: Any) -> str:
        """Prompt enhancement. Returns improved prompt text."""
        raise NotImplementedError(
            f"{self.name} does not implement enhance_prompt")

    # -- health --

    def health_check(self) -> dict:
        """Cheap connectivity/config check. Override for real pings."""
        return {"provider": self.name, "model_id": self.model_id,
                "configured": True}

    def supports(self, feature: str) -> bool:
        return feature in self.capabilities

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "model_id": self.model_id,
            "capabilities": sorted(self.capabilities),
        }
