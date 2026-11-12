"""Design intelligence, AI workflow helpers, Indian-market support, asset library, safety and storage tools."""
from __future__ import annotations

import base64
import datetime as dt
import os
import threading
import time
import uuid

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image

from .core import quality as Q
from .core import studio as S
from .core.jobs import Jobs, call

KINDS = ("icon", "sticker", "illustration", "reference", "logo")


def extend2(r, ctx, pick, need, proj, save_img):
    reg, st = (lambda: ctx.registry), (lambda: ctx.store)
    b64d, b64e = base64.b64decode, lambda b: base64.b64encode(b).decode()

    def margins(body):
        return {"margin_pct": float(body.get("margin_pct", 3)), "bleed_mm": float(body.get("bleed_mm", 0))}

    # ---- design intelligence
    @r.get("/projects/{pid}/check")
    def check(pid: str, margin_pct: float = 3, bleed_mm: float = 0):
        return Q.check_design(proj(pid), margin_pct, bleed_mm)

    @r.post("/projects/{pid}/fix")
    def fix(pid: str, body: dict = Body(default={})):
        p = proj(pid)
        layers, applied = Q.auto_fix(p, **margins(body))
        if applied:
            S.commit(p, layers)  # undoable like any other edit
            st().put("projects", p)
        return {"applied": applied, "report": Q.check_design(p, **margins(body))}

    @r.post("/projects/{pid}/message-check")
    def message_check(pid: str, body: dict = Body(...)):
        need(body, "intended_message")
        q = (f"This is a poster. The intended message is: '{str(body['intended_message'])[:300]}'. In under 80 words: "
             "what does the poster actually communicate, is the intended message clear, and what one change would help most?")
        o = call(reg(), st(), pick("analyze_image", body.get("provider")), "analyze_image",
                 image_bytes=S.to_bytes(S.render_project(proj(pid)), "PNG"), question=q, mime_type="image/png")
        if not o["success"]:
            raise HTTPException(502, o["error"])
        return {"analysis": o["data"], "model_id": o["model_id"]}

    @r.get("/projects/{pid}/compare")
    def compare_versions(pid: str, a: int = 0, b: int = -1):
        p = proj(pid)
        try:
            va, vb = p["versions"][a], p["versions"][b]
        except IndexError:
            raise HTTPException(400, "Version index out of range")
        bg = S.load(b64d(p["bg_base64"])) if p.get("bg_base64") else None
        ia, ib = (S.render(p["width"], p["height"], v, bg).convert("RGB") for v in (va, vb))
        sheet = Image.new("RGB", (ia.width * 2 + 20, ia.height), "white")
        sheet.paste(ia, (0, 0))
        sheet.paste(ib, (ia.width + 20, 0))
        return Response(S.to_bytes(sheet, "PNG"), media_type="image/png")

    def font_names():
        names = []
        for d in (os.path.dirname(S._font_path("x")), getattr(S, "USER_FONT_DIR", None) or ""):
            if d and os.path.isdir(d):
                names += [f for f in os.listdir(d) if f.lower().endswith((".ttf", ".otf"))]
        return sorted(set(names))

    @r.get("/fonts/search")
    def font_search(q: str = ""):
        return [n for n in font_names() if q.lower() in n.lower()]

    @r.get("/font-pairing")
    def pairing(lang: str = "en"):
        head, body = ("NotoSansDevanagari-Variable.ttf",) * 2 if lang == "hi" else ("Poppins-Bold.ttf", "Poppins-Regular.ttf")
        return {"headline_font": head, "body_font": body, "available": {head, body} <= set(font_names()),
                "note": "Chosen from the bundled fonts; upload more with POST /fonts."}

    # ---- AI workflow
    @r.post("/generate/fallback")
    def generate_fallback(body: dict = Body(...)):
        """Opt-in: try providers in the order given. The response always says which one produced the image."""
        need(body, "prompt", "providers")
        names = body["providers"][:4]
        bad = [n for n in names if n not in reg().providers]
        if not names or bad:
            raise HTTPException(400, f"Give 1-4 known providers (unknown: {bad})")
        attempts = []
        for n in names:
            o = call(reg(), st(), n, "generate_image", prompt=body["prompt"],
                     width=body.get("width", 1024), height=body.get("height", 1024))
            attempts.append({"provider": n, "model_id": o["model_id"], "success": o["success"], "error": o["error"]})
            if o["success"]:
                return {"provider_used": n, "fallback_used": len(attempts) > 1, "attempts": attempts,
                        "image_base64": b64e(o["data"])}
        raise HTTPException(502, {"message": "All providers failed", "attempts": attempts})

    @r.get("/jobs")
    def job_list():
        """Lets the editor rediscover running/finished jobs after a page refresh."""
        return [{k: j[k] for k in ("id", "status", "done", "total", "error")} for j in reversed(list(Jobs.recent.values()))]

    @r.post("/prompts")
    def prompt_save(body: dict = Body(...)):
        need(body, "text")
        t = str(body["text"])[:2000]
        return st().put("prompts", {"title": str(body.get("title") or t[:40])[:80], "text": t,
                                    "tags": [str(x)[:30] for x in body.get("tags", [])][:10], "created": time.time()})

    @r.get("/prompts")
    def prompt_list(q: str = ""):
        q = q.lower()
        hit = lambda p: q in (p["title"] + p["text"] + " ".join(p["tags"])).lower()  # noqa: E731
        return sorted((p for p in st().all("prompts") if hit(p)), key=lambda p: -p["created"])

    @r.delete("/prompts/{rid}")
    def prompt_del(rid: str):
        if not st().remove("prompts", rid):
            raise HTTPException(404, "Prompt not found")
        return {"deleted": rid}

    # ---- asset + reference library (icons, stickers, illustrations, reference images, logos)
    @r.post("/assets")
    def asset_add(body: dict = Body(...)):
        need(body, "name", "image_base64")
        kind = body.get("kind", "illustration")
        if kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        try:
            data = Q.safe_image(b64d(body["image_base64"]))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Unsafe or invalid image: {exc}") from exc
        aid, d = uuid.uuid4().hex[:10], os.path.join(reg().output_dir, "assets")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{aid}.png")
        with open(path, "wb") as fh:
            fh.write(data)
        return st().put("assets", {"id": aid, "name": str(body["name"])[:80], "kind": kind, "path": path,
                                   "tags": [str(x)[:30] for x in body.get("tags", [])][:10], "created": time.time()})

    @r.get("/assets")
    def asset_list(q: str = "", kind: str | None = None):
        q = q.lower()
        return [a for a in st().all("assets") if (not kind or a["kind"] == kind)
                and q in (a["name"] + " " + " ".join(a["tags"])).lower()]

    @r.get("/assets/{aid}/image")
    def asset_image(aid: str):
        a = st().get("assets", aid)
        if not a or not os.path.exists(a["path"]):
            raise HTTPException(404, "Asset not found")
        return FileResponse(a["path"], media_type="image/png")

    @r.delete("/assets/{aid}")
    def asset_del(aid: str):
        a = st().get("assets", aid)
        if not a:
            raise HTTPException(404, "Asset not found")
        if os.path.exists(a["path"]):
            os.remove(a["path"])
        st().remove("assets", aid)
        return {"deleted": aid}

    # ---- India: formats, print sizes, verified dates, business presets, recommendations
    @r.post("/format-in")
    def format_in(body: dict = Body(...)):
        lang, digits, out = body.get("lang", "en"), body.get("digits", "latin"), {}
        num = lambda s: s.translate(Q.DEV) if digits == "devanagari" else s  # noqa: E731
        if "amount" in body:
            out["amount"] = num(Q.inr(body["amount"]))
        if "date" in body:
            out["date"] = num(Q.indian_date(dt.date.fromisoformat(body["date"]), lang))
        if not out:
            raise HTTPException(400, "Give amount and/or date (YYYY-MM-DD)")
        return out

    @r.get("/print-sizes")
    def print_sizes():
        b = 2 * Q.mm(3)
        return {k: {"px": v, "mm": [round(v[0] / Q.MM), round(v[1] / Q.MM)], "with_3mm_bleed_px": [v[0] + b, v[1] + b]}
                for k, v in S.SIZES.items() if k.endswith("300dpi")}

    @r.get("/festivals/verified")
    def festivals_verified():
        today = dt.date.today().isoformat()
        return {"dates": [d for d in Q.VERIFIED_DATES if d["date"] >= today],
                "note": "Only dates with a source are listed. Confirm regional and moon-dependent dates before publishing."}

    @r.get("/business-categories")
    def categories():
        return {k: {"name": v["name"], "size": v["size"], "tip": v["tip"]} for k, v in Q.BUSINESS.items()}

    @r.post("/projects/from-category")
    def from_category(body: dict = Body(...)):
        need(body, "category")
        c = Q.BUSINESS.get(body["category"])
        size = body.get("size") or (c or {}).get("size")
        if not c or size not in S.SIZES:
            raise HTTPException(400, "Unknown category or size")
        lang = "hi" if body.get("lang") == "hi" else "en"
        w, h = S.SIZES[size]
        layers = Q.category_layers(c, w, h, str(body.get("business", ""))[:80], body.get("price"), lang,
                                   body.get("digits", "latin"))
        p = st().put("projects", S.new_project(f"{c['name']} poster", w, h, layers))
        return {"id": p["id"], "width": w, "height": h, "layers": layers, "tip": c["tip"]}

    @r.post("/recommend-design")
    def recommend_design(body: dict = Body(...)):
        need(body, "purpose")
        if body["purpose"] not in Q.PURPOSES:
            raise HTTPException(400, f"purpose must be one of {list(Q.PURPOSES)}")
        size, tips = Q.PURPOSES[body["purpose"]]
        c = Q.BUSINESS.get(body.get("category", ""))
        return {"size": size, "tips": tips + ([c["tip"]] if c else []), "palette": c["palette"] if c else None}

    # ---- reliability
    @r.get("/usage/summary")
    def usage_summary():
        errs, by = st().all("errors"), {}
        for e in errs:
            k = f"{e.get('provider')}/{e.get('feature')}"
            by[k] = by.get(k, 0) + 1
        return {"calls_today": st().usage_today(), "errors_logged": len(errs), "errors_by_provider_feature": by}

    @r.post("/storage/cleanup")
    def cleanup(body: dict = Body(default={})):
        """Finds byte-identical images. Dry run by default; never deletes a file the gallery references."""
        dry = body.get("dry_run", True)
        dups = Q.find_duplicates(reg().output_dir, [i["image_path"] for i in st().list_posters()])
        size = sum(os.path.getsize(f) for d in dups for f in d["remove"])
        if not dry:
            for d in dups:
                for f in d["remove"]:
                    os.remove(f)
        return {"dry_run": dry, "groups": len(dups), "reclaimable_bytes": size, "duplicates": dups}

    hrs = reg().config.get("auto_backup_hours")
    if hrs and not getattr(ctx, "_backup_thread", None):
        def loop():
            while True:
                time.sleep(float(hrs) * 3600)
                try:
                    S.backup(reg().output_dir)
                except Exception as exc:  # noqa: BLE001
                    st().log("errors", {"provider": "system", "feature": "auto_backup", "error": str(exc), "attempt": 1})
        ctx._backup_thread = threading.Thread(target=loop, daemon=True)
        ctx._backup_thread.start()
