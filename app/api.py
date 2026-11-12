"""FastAPI application — one endpoint per iimagica feature.

Every endpoint routes through ProviderRegistry, so the model serving it is
whatever config.yaml (or the live /switch call) currently selects.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core.colors import extract_brand_colors
from .core.compose import compose_poster
from .core.extras import remove_background, upscale
from .core.jobs import call
from .core.store import CRITERIA, JsonStore
from .core.registry import (
    FeatureNotSupportedError,
    ProviderRegistry,
    UnknownProviderError,
)

app = FastAPI(
    title="iimagica Testing Platform",
    description="Provider-agnostic model layer: one config-selected model "
                "powers every feature; switching models is a config change.",
    version="1.0.0",
)

# Reuse one registry across requests; allow an env-selected config file.
registry = ProviderRegistry()
store = JsonStore(os.path.join(registry.output_dir, "db.json"))

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def home():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "iimagica Studio is running. Visit /docs or /model-lab."}


def _result_or_404(result):
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)
    return {
        "feature": result.feature,
        "provider": result.provider,
        "model_id": result.model_id,
        "data": result.data if not isinstance(result.data, bytes)
        else None,
        "image_base64": base64.b64encode(result.data).decode()
        if isinstance(result.data, bytes) else None,
        "metadata": {"elapsed_ms": result.metadata.get("elapsed_ms")},
    }


def _timed(feature: str, kwargs: dict):
    start = time.perf_counter()
    result = registry.run(feature, kwargs)
    result.metadata["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return result


def _save_output(feature: str, data: bytes, ext: str = "png") -> str:
    out_dir = os.path.join(registry.output_dir, feature)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{int(time.time() * 1000)}.{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class GenerateRequest(BaseModel):
    prompt: str
    width: int = Field(default=1024, ge=64, le=4096)
    height: int = Field(default=1024, ge=64, le=4096)


class EditRequest(BaseModel):
    prompt: str
    image_base64: str
    mime_type: str = "image/png"


class AnalyzeRequest(BaseModel):
    question: str = "Describe this logo: colors, shapes, style, and mood."
    image_base64: str
    mime_type: str = "image/png"


class LayoutRequest(BaseModel):
    kind: str = Field(pattern="^(frame|footer)$")
    business: str
    details: dict[str, Any] = Field(default_factory=dict)


class EnhanceRequest(BaseModel):
    prompt: str
    context: str = ""


class ColorsRequest(BaseModel):
    image_base64: str
    k: int = Field(default=5, ge=2, le=10)


class ComposeRequest(BaseModel):
    prompt: str = Field(min_length=1)
    business: str = ""
    style: str = ""
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)
    phone: str = ""
    whatsapp: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    cta: str = ""
    footer_position: str = Field(default="bottom", pattern="^(bottom|top)$")
    headline: str = ""
    subheading: str = ""
    footer_style: str = "auto"
    mode: str = Field(default="artwork", pattern="^(artwork|poster)$")
    image_size: str = Field(default="1K", pattern="^(1K|2K|4K)$")
    poster_base64: str | None = None
    logo_base64: str | None = None


class SwitchRequest(BaseModel):
    provider: str


class FeatureOverrideRequest(BaseModel):
    feature: str
    provider: str | None = None  # None → back to default


@app.post("/generate")
def generate(req: GenerateRequest):
    """Feature: generate_image (poster background)."""
    result = _timed("generate_image",
                    {"prompt": req.prompt, "width": req.width,
                     "height": req.height})
    if result.success and isinstance(result.data, bytes):
        result.metadata["saved_to"] = _save_output("generate_image", result.data)
    return _result_or_404(result)


@app.post("/edit")
def edit(req: EditRequest):
    """Feature: edit_image (poster editing / background replace)."""
    result = _timed("edit_image",
                    {"image_bytes": base64.b64decode(req.image_base64),
                     "prompt": req.prompt, "mime_type": req.mime_type})
    if result.success and isinstance(result.data, bytes):
        result.metadata["saved_to"] = _save_output("edit_image", result.data)
    return _result_or_404(result)


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Feature: analyze_image (logo understanding)."""
    result = _timed("analyze_image",
                    {"image_bytes": base64.b64decode(req.image_base64),
                     "question": req.question, "mime_type": req.mime_type})
    return _result_or_404(result)


@app.post("/layout")
def layout(req: LayoutRequest):
    """Feature: suggest_layout (frame or footer design JSON)."""
    result = _timed("suggest_layout",
                    {"kind": req.kind, "business": req.business,
                     "details": req.details})
    return _result_or_404(result)


@app.post("/enhance")
def enhance(req: EnhanceRequest):
    """Feature: enhance_prompt."""
    result = _timed("enhance_prompt",
                    {"prompt": req.prompt, "context": req.context})
    return _result_or_404(result)


@app.post("/colors")
def colors(req: ColorsRequest):
    """Brand color extraction — pure code (k-means), no model involved."""
    return extract_brand_colors(base64.b64decode(req.image_base64), k=req.k)


@app.post("/compose")
def compose(req: ComposeRequest):
    """Prompt -> poster + frame + footer + final image, in one call."""
    logo = None
    if req.logo_base64:
        try:
            logo = base64.b64decode(req.logo_base64)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid logo_base64") from exc
    details = {k: getattr(req, k) for k in
               ("phone", "whatsapp", "email", "website", "address", "cta")}
    poster = None
    if req.poster_base64:
        try:
            poster = base64.b64decode(req.poster_base64)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid poster_base64") from exc
    out = compose_poster(registry, req.prompt, req.business, details, logo,
                         req.style, req.width, req.height, req.footer_position,
                         headline=req.headline, subheading=req.subheading,
                         footer_style=req.footer_style, mode=req.mode,
                         image_size=req.image_size, poster_bytes=poster)
    if not out["success"]:
        raise HTTPException(status_code=502, detail=out["error"])
    out["final_image_base64"] = base64.b64encode(out.pop("final_bytes")).decode()
    return out


@app.get("/models")
def models():
    """Registered providers, capabilities and current per-feature selection."""
    return registry.list_models()


@app.post("/switch")
def switch(req: SwitchRequest):
    """Change the default provider for ALL features at runtime."""
    try:
        return registry.switch_default(req.provider)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/feature-override")
def feature_override(req: FeatureOverrideRequest):
    """Point ONE feature at a different provider (or back to default)."""
    try:
        return registry.set_feature_provider(req.feature, req.provider)
    except (UnknownProviderError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"default_provider": registry.default_provider,
            "providers": {name: p.health_check()
                          for name, p in registry.providers.items()}}


# ---- code-only utilities ---------------------------------------------------
def _b64(value: str) -> bytes:
    try:
        return base64.b64decode(value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc


class RemoveBgRequest(BaseModel):
    image_base64: str
    tolerance: int = Field(40, ge=0, le=150)


class UpscaleRequest(BaseModel):
    image_base64: str
    scale: int = Field(2, ge=1, le=4)


@app.post("/remove-bg")
def remove_bg(req: RemoveBgRequest):
    out = remove_background(_b64(req.image_base64), req.tolerance)
    return {"image_base64": base64.b64encode(out).decode()}


@app.post("/upscale")
def upscale_image(req: UpscaleRequest):
    out = upscale(_b64(req.image_base64), req.scale)
    return {"image_base64": base64.b64encode(out).decode()}


# ---- Model Lab: compare, rate, leaderboard ---------------------------------
class CompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    providers: list[str] = Field(..., min_length=1, max_length=6)
    width: int = Field(1024, ge=256, le=2048)
    height: int = Field(1024, ge=256, le=2048)


class RateRequest(BaseModel):
    provider: str
    scores: dict[str, int]


@app.post("/compare")
def compare(req: CompareRequest):
    """Same prompt on several providers; records time, errors and images."""
    unknown = [p for p in req.providers if p not in registry.providers]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown providers: {unknown}")
    results = []
    for name in req.providers:
        o = call(registry, store, name, "generate_image", retries=1,
                 prompt=req.prompt, width=req.width, height=req.height)
        row = {"provider": name, "model_id": o["model_id"], "success": o["success"],
               "error": o["error"], "image_path": None, "elapsed_ms": o["elapsed_ms"],
               "attempts": o["attempts"], "est_cost": o["est_cost"]}
        if o["success"] and isinstance(o["data"], bytes):
            row["image_path"] = _save_output(f"compare/{name}", o["data"])
        results.append(row)
    return store.add_comparison(req.prompt, results)


@app.get("/compare/history")
def compare_history():
    return store.history()


@app.post("/compare/{cid}/rate")
def rate(cid: str, req: RateRequest):
    try:
        if not store.rate(cid, req.provider, req.scores):
            raise HTTPException(status_code=404, detail="Comparison/provider not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "criteria": CRITERIA}


@app.get("/leaderboard")
def leaderboard():
    return store.leaderboard()


# ---- Gallery ---------------------------------------------------------------
class GalleryAddRequest(BaseModel):
    image_base64: str
    title: str = ""
    tags: list[str] = []
    meta: dict[str, Any] = {}


@app.post("/gallery")
def gallery_add(req: GalleryAddRequest):
    path = _save_output("gallery", _b64(req.image_base64))
    return store.add_poster(path, req.title, req.tags, req.meta)


@app.get("/gallery")
def gallery_list(q: str = "", favorite: bool | None = None):
    return store.list_posters(q, favorite)


@app.post("/gallery/{pid}/favorite")
def gallery_favorite(pid: str):
    rec = store.toggle_favorite(pid)
    if rec is None:
        raise HTTPException(status_code=404, detail="Poster not found")
    return rec


@app.delete("/gallery/{pid}")
def gallery_delete(pid: str):
    if not store.delete_poster(pid):
        raise HTTPException(status_code=404, detail="Poster not found")
    return {"deleted": pid}


# ---- studio / lab / platform routes (see routes_studio.py) ------------------
import sys  # noqa: E402

from .routes_studio import build_router  # noqa: E402

app.include_router(build_router(sys.modules[__name__]))

from .routes_lab import build_lab_router  # noqa: E402
app.include_router(build_lab_router(sys.modules[__name__]))

from .guard import dedupe_middleware  # noqa: E402
app.middleware("http")(dedupe_middleware)
