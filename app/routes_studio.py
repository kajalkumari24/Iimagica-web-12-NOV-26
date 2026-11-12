"""Studio, Model Lab and platform routes. Handlers stay thin; logic is in core/."""
from __future__ import annotations

import base64
import csv
import io
import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .core import studio as S
from .core.colors import extract_brand_colors
from .core.jobs import Jobs, call

jobs = Jobs()


def b64d(v: str) -> bytes:
    try:
        return base64.b64decode(v)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Invalid base64") from exc


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def img_resp(img, fmt="PNG", dpi=300):
    return {"format": fmt.upper(), "width": img.width, "height": img.height,
            "image_base64": b64e(S.to_bytes(img, fmt, dpi))}


def build_router(ctx) -> APIRouter:
    """ctx is the app.api module (registry/store are read lazily)."""
    r = APIRouter()
    reg = lambda: ctx.registry
    st = lambda: ctx.store

    def pick(feature, name=None):
        if name:
            if name not in reg().providers:
                raise HTTPException(400, f"Unknown provider {name}")
            return name
        try:
            return reg()._resolve_feature_provider(feature).name
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc

    def need(d: dict, *keys):
        miss = [k for k in keys if k not in d]
        if miss:
            raise HTTPException(400, f"Missing: {miss}")

    def proj(pid):
        p = st().get("projects", pid)
        if not p:
            raise HTTPException(404, "Project not found")
        return p

    def save_img(feature, data):
        return ctx._save_output(feature, data)

    # ---------- 1-4 variations, bulk, jobs
    @r.post("/variations")
    def variations(body: dict = Body(...)):
        """4-8 variations of one prompt as a background job (poll /jobs/{id})."""
        need(body, "prompt")
        n = int(body.get("n", 4))
        if not 4 <= n <= 8:
            raise HTTPException(400, "n must be 4-8")
        name = pick("generate_image", body.get("provider"))
        w, h = int(body.get("width", 1024)), int(body.get("height", 1024))

        def work():
            for i in range(n):
                o = call(reg(), st(), name, "generate_image",
                         prompt=f"{body['prompt']}. Variation {i + 1}: different composition.",
                         width=w, height=h)
                yield {"index": i, "success": o["success"], "error": o["error"],
                       "elapsed_ms": o["elapsed_ms"], "attempts": o["attempts"],
                       "image_path": save_img("variations", o["data"]) if o["success"] and isinstance(o["data"], bytes) else None}
        return {"job_id": jobs.start(n, work, bool(body.get("wait")))}

    @r.post("/bulk")
    def bulk(body: dict = Body(...)):
        """items: [{prompt, width?, height?}] generated as one job."""
        need(body, "items")
        items = body["items"]
        if not items or len(items) > 100:
            raise HTTPException(400, "items must hold 1-100 entries")
        name = pick("generate_image", body.get("provider"))

        def work():
            for it in items:
                o = call(reg(), st(), name, "generate_image", prompt=it["prompt"],
                         width=int(it.get("width", 1024)), height=int(it.get("height", 1024)))
                yield {"prompt": it["prompt"], "success": o["success"], "error": o["error"],
                       "image_path": save_img("bulk", o["data"]) if o["success"] and isinstance(o["data"], bytes) else None}
        return {"job_id": jobs.start(len(items), work, bool(body.get("wait")))}

    @r.get("/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if not j:
            raise HTTPException(404, "Job not found")
        return {**j, "progress": round(j["done"] / max(1, j["total"]), 2)}

    # ---------- 10-12 image tools
    @r.post("/replace-background")
    def replace_bg(body: dict = Body(...)):
        need(body, "image_base64", "prompt")
        name = pick("edit_image", body.get("provider"))
        o = call(reg(), st(), name, "edit_image", image_bytes=b64d(body["image_base64"]),
                 prompt=f"Keep the main subject unchanged. Replace the background with: {body['prompt']}")
        if not o["success"]:
            raise HTTPException(502, o["error"])
        return {"image_base64": b64e(o["data"]), "elapsed_ms": o["elapsed_ms"]}

    @r.post("/remove-object")
    def remove_object(body: dict = Body(...)):
        need(body, "image_base64", "description")
        name = pick("edit_image", body.get("provider"))
        o = call(reg(), st(), name, "edit_image", image_bytes=b64d(body["image_base64"]),
                 prompt=f"Remove {body['description']} and fill the area naturally. Change nothing else.")
        if not o["success"]:
            raise HTTPException(502, o["error"])
        return {"image_base64": b64e(o["data"]), "elapsed_ms": o["elapsed_ms"]}

    @r.post("/expand")
    def expand(body: dict = Body(...)):
        need(body, "image_base64")
        img = S.expand(S.load(b64d(body["image_base64"])),
                       *(int(body.get(k, 0)) for k in ("left", "right", "top", "bottom")))
        if body.get("ai"):  # let an edit model repaint the blurred borders
            name = pick("edit_image", body.get("provider"))
            o = call(reg(), st(), name, "edit_image", image_bytes=S.to_bytes(img, "PNG"),
                     prompt="Extend the scene naturally into the blurred border areas. Keep the centre unchanged.")
            if not o["success"]:
                raise HTTPException(502, o["error"])
            img = S.load(o["data"])
        return img_resp(img)

    # ---------- 14-16 brand kits
    @r.post("/brands")
    def brand_save(body: dict = Body(...)):
        """name, colors?, logo_base64?, contacts?. Colours auto-extracted from the logo."""
        need(body, "name")
        if body.get("logo_base64") and not body.get("colors"):
            body["colors"] = extract_brand_colors(b64d(body["logo_base64"]), 5, True)["colors"][:4]
        return st().put("brands", body)

    @r.get("/brands")
    def brand_list():
        return [{k: v for k, v in b.items() if k != "logo_base64"} for b in st().all("brands")]

    @r.get("/brands/{bid}")
    def brand_get(bid: str):
        b = st().get("brands", bid)
        if not b:
            raise HTTPException(404, "Brand not found")
        return b

    @r.delete("/brands/{bid}")
    def brand_del(bid: str):
        if not st().remove("brands", bid):
            raise HTTPException(404, "Brand not found")
        return {"deleted": bid}

    # ---------- 17 QR
    @r.post("/qr")
    def qr(body: dict = Body(...)):
        need(body, "data")
        try:
            import qrcode
        except ImportError as exc:
            raise HTTPException(501, "pip install qrcode") from exc
        data = body["data"]
        if body.get("whatsapp"):
            data = "https://wa.me/" + "".join(c for c in data if c.isdigit())
        img = qrcode.make(data).convert("RGB").resize((int(body.get("size", 400)),) * 2)
        return img_resp(img)

    # ---------- 19-21, 48 festivals, languages, captions
    @r.get("/festivals")
    def fest(region: str | None = None, days: int = 45):
        return S.festivals(dt.date.today(), days, region)

    @r.get("/suggestions")
    def sugg(region: str | None = None, days: int = 30):
        return S.suggestions(dt.date.today(), region, days)

    @r.get("/languages")
    def langs():
        return S.LANGUAGES

    @r.post("/captions")
    def caps(body: dict = Body(...)):
        need(body, "occasion")
        return {"captions": S.captions(body["occasion"], body.get("business", ""),
                                       body.get("tone", "friendly"), body.get("lang", "en"),
                                       body.get("cta", ""))}

    # ---------- 5-9, 13, 23-25 projects
    @r.get("/templates")
    def templates():
        return S.TEMPLATES

    @r.post("/projects")
    def project_new(body: dict = Body(...)):
        """name, size (key of social sizes) or width/height, template?, brand_id?, text?, bg_base64?"""
        w, h = S.SIZES.get(body.get("size", ""), (int(body.get("width", 1080)), int(body.get("height", 1350))))
        brand = st().get("brands", body["brand_id"]) if body.get("brand_id") else None
        layers = S.template_layers(body["template"], w, h, brand, body.get("text", "")) if body.get("template") else []
        return st().put("projects", S.new_project(body.get("name", "Untitled"), w, h, layers, body.get("bg_base64")))

    @r.get("/projects")
    def project_list(q: str = "", favorite: bool | None = None):
        out = [p for p in st().all("projects") if q.lower() in p["name"].lower()
               and (favorite is None or p["favorite"] == favorite)]
        return [{k: p[k] for k in ("id", "name", "width", "height", "favorite", "updated")} for p in out]

    @r.get("/projects/{pid}")
    def project_get(pid: str):
        p = proj(pid)
        return {**{k: v for k, v in p.items() if k not in ("versions", "bg_base64")},
                "layers": S.current(p), "version_count": len(p["versions"])}

    @r.post("/projects/{pid}/ops")
    def project_op(pid: str, body: dict = Body(...)):
        p = proj(pid)
        body.setdefault("canvas", [p["width"], p["height"]])
        try:
            S.commit(p, S.apply_op(S.current(p), body))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        st().put("projects", p)
        return {"layers": S.current(p), "cursor": p["cursor"], "version_count": len(p["versions"])}

    @r.post("/projects/{pid}/undo")
    def project_undo(pid: str):
        p = S.undo(proj(pid))
        st().put("projects", p)
        return {"layers": S.current(p), "cursor": p["cursor"]}

    @r.post("/projects/{pid}/redo")
    def project_redo(pid: str):
        p = S.redo(proj(pid))
        st().put("projects", p)
        return {"layers": S.current(p), "cursor": p["cursor"]}

    @r.post("/projects/{pid}/duplicate")
    def project_dup(pid: str):
        p = proj(pid)
        c = S.new_project(p["name"] + " copy", p["width"], p["height"], S.current(p), p.get("bg_base64"))
        return st().put("projects", c)

    @r.post("/projects/{pid}/favorite")
    def project_fav(pid: str):
        p = proj(pid)
        p["favorite"] = not p["favorite"]
        st().put("projects", p)
        return {"favorite": p["favorite"]}

    @r.delete("/projects/{pid}")
    def project_del(pid: str):
        if not st().remove("projects", pid):
            raise HTTPException(404, "Project not found")
        return {"deleted": pid}

    @r.post("/projects/{pid}/render")
    def project_render(pid: str, body: dict = Body(default={})):
        """format PNG|JPG|PDF, dpi, sizes? (social size keys, mode cover|blur_pad)."""
        p = proj(pid)
        img = S.render_project(p, transparent=bool(body.get("transparent")) and not body.get("sizes"))
        fmt, dpi = body.get("format", "PNG"), int(body.get("dpi", 300))
        if body.get("sizes"):
            bad = [s for s in body["sizes"] if s not in S.SIZES]
            if bad:
                raise HTTPException(400, f"Unknown sizes {bad}; valid: {sorted(S.SIZES)}")
            return {s: img_resp(S.resize_to(img, *S.SIZES[s], body.get("mode", "blur_pad")), fmt, dpi)
                    for s in body["sizes"]}
        try:
            return img_resp(img, fmt, dpi)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @r.post("/projects/{pid}/layers/{lid}/regenerate")
    def layer_regen(pid: str, lid: str, body: dict = Body(...)):
        """Selective regeneration: new AI image for one image layer only."""
        need(body, "prompt")
        p = proj(pid)
        L = next((l for l in S.current(p) if l["id"] == lid), None)
        if not L or L["type"] != "image":
            raise HTTPException(404, "Image layer not found")
        if L["locked"]:
            raise HTTPException(403, "Layer is locked")
        name = pick("generate_image", body.get("provider"))
        o = call(reg(), st(), name, "generate_image", prompt=body["prompt"],
                 width=max(256, L["w"]), height=max(256, L["h"]))
        if not o["success"]:
            raise HTTPException(502, o["error"])
        S.commit(p, S.apply_op(S.current(p), {"op": "update", "id": lid, "changes": {"src_base64": b64e(o["data"])}}))
        st().put("projects", p)
        return {"layers_version": p["cursor"]}

    # ---------- 18, 45-47 analysis
    @r.post("/layout-suggest")
    def layout_suggest(body: dict = Body(...)):
        need(body, "image_base64")
        return S.text_regions(S.load(b64d(body["image_base64"])))

    @r.post("/evaluate")
    def evaluate(body: dict = Body(...)):
        need(body, "image_base64")
        return S.evaluate(S.load(b64d(body["image_base64"])))

    @r.post("/brand-check")
    def brand_check(body: dict = Body(...)):
        need(body, "image_base64")
        colors = body.get("colors") or (st().get("brands", body.get("brand_id", "")) or {}).get("colors")
        if not colors:
            raise HTTPException(400, "Give colors or a valid brand_id")
        return S.brand_check(S.load(b64d(body["image_base64"])), colors)

    # ---------- 28-38 benchmarking
    @r.post("/benchmark")
    def benchmark(body: dict = Body(...)):
        """feature: generate_image | edit_image | enhance_prompt; repeats 1-10; background job."""
        need(body, "prompt", "providers")
        feat = body.get("feature", "generate_image")
        if feat not in ("generate_image", "edit_image", "enhance_prompt"):
            raise HTTPException(400, "feature must be generate_image, edit_image or enhance_prompt")
        bad = [p for p in body["providers"] if p not in reg().providers]
        if bad:
            raise HTTPException(400, f"Unknown providers {bad}")
        reps = max(1, min(10, int(body.get("repeats", 1))))
        kw = {"prompt": body["prompt"]}
        if feat == "generate_image":
            kw.update(width=int(body.get("width", 1024)), height=int(body.get("height", 1024)))
        if feat == "edit_image":
            need(body, "image_base64")
            kw["image_bytes"] = b64d(body["image_base64"])
        total = len(body["providers"]) * reps

        def work():
            rows = []
            for name in body["providers"]:
                for rep in range(reps):
                    o = call(reg(), st(), name, feat, retries=int(body.get("retries", 1)), **kw)
                    row = {"provider": name, "model_id": o["model_id"], "success": o["success"],
                           "error": o["error"], "elapsed_ms": o["elapsed_ms"], "attempts": o["attempts"],
                           "est_cost": o["est_cost"], "repeat": rep, "image_path": None}
                    if o["success"] and isinstance(o["data"], bytes):
                        row["image_path"] = save_img(f"benchmark/{name}", o["data"])
                    elif o["success"]:
                        row["output"] = str(o["data"])[:500]
                    rows.append(row)
                    yield row
            st().add_comparison(f"[{feat}] {body['prompt']}", rows)
        return {"job_id": jobs.start(total, work, bool(body.get("wait")))}

    @r.get("/reports/benchmark")
    def report(format: str = "json"):
        rows = st().leaderboard()
        if format == "json":
            return rows
        if format != "csv":
            raise HTTPException(400, "format must be json or csv")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["provider", "runs", "success_rate", "avg_ms", "overall", "total_est_cost"])
        costs = {}
        for c in st().history():
            for x in c["results"]:
                costs[x["provider"]] = costs.get(x["provider"], 0) + (x.get("est_cost") or 0)
        for x in rows:
            w.writerow([x["provider"], x["runs"], x["success_rate"], x["avg_ms"], x["overall"],
                        round(costs.get(x["provider"], 0), 4)])
        return Response(buf.getvalue(), media_type="text/csv")

    @r.get("/quota")
    def quota():
        """Today's calls per provider vs optional daily_limit in config.yaml."""
        used = st().usage_today()
        cfg = reg().config.get("providers") or {}
        return {n: {"used_today": used.get(n, 0), "daily_limit": (cfg.get(n) or {}).get("daily_limit"),
                    "remaining": None if (cfg.get(n) or {}).get("daily_limit") is None
                    else max(0, cfg[n]["daily_limit"] - used.get(n, 0))} for n in reg().providers}

    @r.get("/errors")
    def errors(limit: int = 50):
        return st().all("errors")[-limit:][::-1]

    # ---------- 43 backup, 50 campaigns
    @r.post("/backup")
    def backup():
        return {"path": S.backup(reg().output_dir)}

    @r.post("/restore")
    def restore(body: dict = Body(...)):
        need(body, "name")
        try:
            return {"files_restored": S.restore(reg().output_dir, body["name"])}
        except FileNotFoundError as exc:
            raise HTTPException(404, "Backup not found") from exc

    @r.post("/campaigns")
    def campaign_new(body: dict = Body(...)):
        """name, prompt, scheduled_for (YYYY-MM-DD), brand_id?"""
        need(body, "name", "prompt", "scheduled_for")
        try:
            dt.date.fromisoformat(body["scheduled_for"])
        except ValueError as exc:
            raise HTTPException(400, "scheduled_for must be YYYY-MM-DD") from exc
        return st().put("campaigns", {**body, "status": "scheduled"})

    @r.get("/campaigns")
    def campaign_list():
        return st().all("campaigns")

    @r.post("/campaigns/run-due")
    def campaign_run():
        """Generate every scheduled campaign due today or earlier (call from a cron)."""
        done = []
        name = pick("generate_image")
        for c in st().all("campaigns"):
            if c["status"] == "scheduled" and c["scheduled_for"] <= dt.date.today().isoformat():
                o = call(reg(), st(), name, "generate_image", prompt=c["prompt"], width=1080, height=1350)
                c["status"] = "done" if o["success"] else "failed"
                c["error"] = o["error"]
                if o["success"] and isinstance(o["data"], bytes):
                    c["image_path"] = save_img("campaigns", o["data"])
                st().put("campaigns", c)
                done.append({"id": c["id"], "status": c["status"]})
        return done

    from .routes_more import extend
    extend(r, ctx, pick, need, proj, save_img)
    from .routes_quality import extend2
    extend2(r, ctx, pick, need, proj, save_img)
    return r
