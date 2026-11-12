"""Provider registry — loads config.yaml, instantiates providers, resolves
which provider serves which feature, and supports live runtime switching.

The rest of the application talks ONLY to this registry and BaseProvider.
Swapping models = editing config.yaml or POST /switch. Nothing else changes.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

import yaml

try:  # load GEMINI_API_KEY / FLUX_API_KEY / STABILITY_API_KEY from .env
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .base import BaseProvider, FEATURES, GenerationResult

CONFIG_PATH = os.environ.get("IIMAGICA_CONFIG",
                             os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))


class FeatureNotSupportedError(Exception):
    """Raised when the selected provider cannot serve a feature."""


class UnknownProviderError(Exception):
    """Raised when switching to a provider name that is not registered."""


class ProviderRegistry:
    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or CONFIG_PATH
        with open(self.config_path, "r", encoding="utf-8") as fh:
            self.config: dict[str, Any] = yaml.safe_load(fh)
        self.providers: dict[str, BaseProvider] = {}
        self._load_providers()
        self.default_provider: str = self.config.get("default_provider", "")
        self.features: dict[str, str | None] = self.config.get("features", {})
        self.output_dir: str = self.config.get("output_dir", "outputs")

    # ------------------------------------------------------------------ load
    def _load_providers(self) -> None:
        for name, spec in (self.config.get("providers") or {}).items():
            if not spec.get("enabled", True):
                continue
            dotted_path: str = spec["class"]
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            # API key comes from the environment variable named in config —
            # the key value itself never lives in config files.
            api_key = os.environ.get(spec.get("api_key_env", ""), "")
            self.providers[name] = cls(
                model_id=spec.get("model_id", cls.model_id),
                api_key=api_key,
            )

    # --------------------------------------------------------------- resolve
    def _resolve_feature_provider(self, feature: str) -> BaseProvider:
        chosen = self.features.get(feature) or self.default_provider
        provider = self.providers.get(chosen)
        if provider is None:
            raise UnknownProviderError(
                f"Provider '{chosen}' (feature '{feature}') is not registered. "
                f"Registered: {sorted(self.providers)}")
        if not provider.supports(feature):
            raise FeatureNotSupportedError(
                f"Provider '{chosen}' does not support '{feature}'. "
                f"Capabilities: {sorted(provider.capabilities)}")
        return provider

    def run(self, feature: str, method_kwargs: dict) -> "GenerationResult":
        """Execute a feature through the selected provider, normalized."""
        provider = self._resolve_feature_provider(feature)
        try:
            data = getattr(provider, feature)(**method_kwargs)
        except Exception as exc:  # noqa: BLE001 — normalized failure shape
            return GenerationResult(
                feature=feature, provider=provider.name,
                model_id=provider.model_id, success=False, error=str(exc))
        return GenerationResult(
            feature=feature, provider=provider.name,
            model_id=provider.model_id, success=True, data=data)

    # --------------------------------------------------------------- switching
    # ------------------------------------------------------------ persistence
    def _persist(self) -> None:
        """Write the current selection back to config.yaml, so a model
        switch survives restarts and needs no code change."""
        self.config["default_provider"] = self.default_provider
        self.config["features"] = dict(self.features)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.config, fh, sort_keys=False)

    def switch_default(self, name: str) -> dict:
        if name not in self.providers:
            raise UnknownProviderError(
                f"Unknown provider '{name}'. Registered: {sorted(self.providers)}")
        self.default_provider = name
        self._persist()
        return {"default_provider": name,
                "model_id": self.providers[name].model_id}

    def set_feature_provider(self, feature: str, name: str | None) -> dict:
        if name is not None and name not in self.providers:
            raise UnknownProviderError(
                f"Unknown provider '{name}'. Registered: {sorted(self.providers)}")
        if feature not in FEATURES:
            raise UnknownProviderError(
                f"Unknown feature '{feature}'. Features: {sorted(FEATURES)}")
        self.features[feature] = name
        self._persist()
        return {feature: name or f"default({self.default_provider})"}

    def model_for(self, feature: str) -> str:
        return self._resolve_feature_provider(feature).model_id

    # ------------------------------------------------------------------ info
    def list_models(self) -> dict:
        return {
            "default_provider": self.default_provider,
            "features": dict(self.features),
            "providers": {n: p.as_dict() for n, p in self.providers.items()},
        }
