"""Gap-filling routes: fonts, dashboard, footer designer, brand apply, resize/convert,
campaign sets, batch export, region edit, style transfer, proofread, translate, model advice."""
from __future__ import annotations

import base64
import copy
import io
import os
import zipfile

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image

from .core import quality as Q
from .core import studio as S
from .core.jobs import call


def extend(r, ctx, pick, need, proj, save_img):
    reg, st = (lambda: ctx.registry), (lambda: ctx.store)
    b64d = lambda v: base64.b64decode(v)
    b64e = lambda b: base64.b64encode(b).decode()

    def fonts_dir():
        d = os.path.join(reg().output_dir, "fonts")
        os.makedirs(d, exist_ok=True)
        S.USER_FONT_DIR = d
        return d

    def ai(feature, **kw):
        o = call(reg(), st(), pick(feature, kw.pop("provider", None)), feature, **kw)
        if not o["success"]:
            raise HTTPException(502, o["error"])
        return o["data"]

    def brand_of(bid):
        b = st().get("brands", bid or "")
        if not b:
            raise HTTPException(404, "Brand not found")
        return b

    def new_from(p, name, w, h, layers):
        return st().put("projects", S.new_project(name, w, h, layers, p.get("bg_base64")))

    # ---- editor page + fonts
    @r.get("/editor")
    def editor():
        return FileResponse(os.path.join(os.path.dirname(__file__), "static", "editor.html"))

    @r.get("/size-list")
    def size_list():
        return S.SIZES

    @r.get("/fonts")
    def fonts():
        fonts_dir()
        names = lambda d: sorted(f for f in os.listdir(d) if f.lower().endswith((".ttf", ".otf")))
        return {"bundled": names(os.path.dirname(S._font_path("x"))), "uploaded": names(S.USER_FONT_DIR)}

    @r.post("/fonts")
    def font_upload(body: dict = Body(...)):
        need(body, "name", "font_base64")
        name = os.path.basename(body["name"])
        if not name.lower().endswith((".ttf", ".otf")):
            raise HTTPException(400, "Only .ttf/.otf fonts")
        try:
            Q.check_font(b64d(body["font_base64"]))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Rejected font: {exc}") from exc
        with open(os.path.join(fonts_dir(), name), "wb") as fh:
            fh.write(b64d(body["font_base64"]))
        return {"saved": name}

    # ---- projects dashboard
    @r.get("/dashboard")
    def dashboard(q: str = "", folder: str | None = None, favorite: bool | None = None,
                  sort: str = "updated", order: str = "desc"):
        items = [p for p in st().all("projects") if q.lower() in p["name"].lower()
                 and (folder is None or p.get("folder") == folder)
                 and (favorite is None or p["favorite"] == favorite)]
        if sort not in ("updated", "created", "name"):
            raise HTTPException(400, "sort: updated|created|name")
        items.sort(key=lambda p: p[sort].lower() if sort == "name" else p[sort], reverse=order == "desc")
        return [{**{k: p.get(k) for k in ("id", "name", "width", "height", "favorite", "folder", "updated")},
                 "versions": len(p["versions"])} for p in items]

    @r.get("/folders")
    def folders():
        return sorted({p.get("folder") for p in st().all("projects") if p.get("folder")})

    @r.post("/projects/{pid}/meta")
    def meta(pid: str, body: dict = Body(...)):
        p = proj(pid)
        for k in ("name", "folder"):
            if k in body:
                p[k] = body[k]
        st().put("projects", p)
        return {"name": p["name"], "folder": p.get("folder")}

    @r.get("/projects/{pid}/thumbnail")
    def thumb(pid: str):
        img = S.render_project(proj(pid))
        img.thumbnail((320, 320))
        return Response(S.to_bytes(img, "PNG", 72), media_type="image/png")

    @r.get("/projects/{pid}/bg")
    def bg_get(pid: str):
        p = proj(pid)
        if not p.get("bg_base64"):
            raise HTTPException(404, "No background")
        return Response(b64d(p["bg_base64"]), media_type="image/png")

    @r.post("/projects/{pid}/bg")
    def bg_set(pid: str, body: dict = Body(...)):
        """image_base64, or prompt (AI generates the background)."""
        p = proj(pid)
        if body.get("prompt"):
            data = ai("generate_image", provider=body.get("provider"), prompt=body["prompt"],
                      width=p["width"], height=p["height"])
        elif body.get("image_base64"):
            try:
                data = Q.safe_image(b64d(body["image_base64"]))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, f"Unsafe or invalid image: {exc}") from exc
        else:
            raise HTTPException(400, "Give image_base64 or prompt")
        p["bg_base64"] = b64e(data)
        st().put("projects", p)
        return {"ok": True}

    @r.get("/projects/{pid}/versions")
    def versions(pid: str):
        p = proj(pid)
        return {"cursor": p["cursor"], "versions": [{"index": i, "layers": len(v)} for i, v in enumerate(p["versions"])]}

    @r.post("/projects/{pid}/restore")
    def restore_version(pid: str, body: dict = Body(...)):
        """Non-destructive: copies an old version on top as a new version."""
        p = proj(pid)
        i = int(body.get("index", -1))
        if not 0 <= i < len(p["versions"]):
            raise HTTPException(400, "Bad version index")
        S.commit(p, copy.deepcopy(p["versions"][i]))
        st().put("projects", p)
        return {"cursor": p["cursor"]}

    # ---- footer designer + presets
    @r.post("/projects/{pid}/footer")
    def footer(pid: str, body: dict = Body(...)):
        """layout bottom|top|left|right|full, style solid|wave|ribbon|glass|frame, brand_id?, contacts?, preset_id?, qr?"""
        p = proj(pid)
        spec = dict(st().get("footer_presets", body["preset_id"]) or {}) if body.get("preset_id") else {}
        spec.update({k: v for k, v in body.items() if k != "preset_id"})
        brand = brand_of(spec["brand_id"]) if spec.get("brand_id") else {}
        contacts = {"name": brand.get("name"), **(brand.get("contacts") or {}), **(spec.get("contacts") or {})}
        try:
            fl = S.footer_layers(spec.get("layout", "bottom"), p["width"], p["height"], contacts,
                                 spec.get("colors") or brand.get("colors") or [], spec.get("style", "solid"),
                                 brand.get("font"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if spec.get("qr") and (contacts.get("website") or contacts.get("whatsapp")):
            try:
                import qrcode
                data = contacts.get("website") or "https://wa.me/" + "".join(c for c in contacts["whatsapp"] if c.isdigit())
                buf = io.BytesIO()
                qrcode.make(data).convert("RGB").save(buf, "PNG")
                bar = fl[0]
                sz = int(min(bar["h"], p["width"] * .14) * .9)
                fl.append(S.new_layer(type="image", name="Footer QR", footer=True, src_base64=b64e(buf.getvalue()),
                                      x=bar["x"] + bar["w"] - sz - 20, y=bar["y"] + (bar["h"] - sz) // 2, w=sz, h=sz))
            except ImportError:
                pass
        keep = [l for l in S.current(p) if not l.get("footer")]
        S.commit(p, keep + fl)
        st().put("projects", p)
        return {"layers": S.current(p)}

    @r.post("/footer-presets")
    def preset_save(body: dict = Body(...)):
        need(body, "name")
        body.pop("contacts", None)  # presets hold design only
        return st().put("footer_presets", body)

    @r.get("/footer-presets")
    def preset_list():
        return st().all("footer_presets")

    @r.delete("/footer-presets/{fid}")
    def preset_del(fid: str):
        if not st().remove("footer_presets", fid):
            raise HTTPException(404, "Preset not found")
        return {"deleted": fid}

    @r.post("/projects/{pid}/apply-brand")
    def apply_brand(pid: str, body: dict = Body(...)):
        p = proj(pid)
        bg = S.load(b64d(p["bg_base64"])) if p.get("bg_base64") else None
        base = S.render(p["width"], p["height"], [l for l in S.current(p) if l.get("name") != "Logo"], bg)
        S.commit(p, S.apply_brand(S.current(p), p["width"], p["height"], brand_of(body.get("brand_id")), base))
        st().put("projects", p)
        return {"layers": [{k: v for k, v in l.items() if k != "src_base64"} for l in S.current(p)]}

    # ---- multi-size, conversion, campaign sets, batch export
    def size_of(key):
        if key not in S.SIZES:
            raise HTTPException(400, f"Unknown size {key}; valid: {sorted(S.SIZES)}")
        return S.SIZES[key]

    @r.post("/projects/{pid}/resize")
    def resize(pid: str, body: dict = Body(...)):
        """Re-layout one design into new editable projects, one per size key."""
        need(body, "sizes")
        p, out = proj(pid), []
        for k in body["sizes"]:
            w, h = size_of(k)
            out.append(new_from(p, f"{p['name']} - {k}", w, h, S.scale_layers(S.current(p), w / p["width"], h / p["height"]))["id"])
        return {"project_ids": out}

    @r.post("/projects/{pid}/convert")
    def convert(pid: str, body: dict = Body(...)):
        """festivals x languages x sizes -> new projects (headline swapped for the greeting)."""
        p = proj(pid)
        fests, langs, sizes = body.get("festivals") or [None], body.get("languages") or ["en"], body.get("sizes") or [None]
        if len(fests) * len(langs) * len(sizes) > 40:
            raise HTTPException(400, "Max 40 designs per call")
        out = []
        for f in fests:
            for lg in langs:
                for k in sizes:
                    w, h = size_of(k) if k else (p["width"], p["height"])
                    layers = S.scale_layers(S.current(p), w / p["width"], h / p["height"])
                    if f:
                        for l in layers:
                            if l["type"] == "text" and l.get("name") in ("Headline", "Title"):
                                l["text"] = S.greeting(f, lg)
                    out.append(new_from(p, f"{p['name']} - {f or 'orig'} - {lg} - {k or 'same'}", w, h, layers)["id"])
        return {"project_ids": out}

    @r.post("/campaign-set")
    def campaign_set(body: dict = Body(...)):
        """One brief -> many posters. brief{headline}, templates[], sizes[], brand_id?, bg_prompt?"""
        need(body, "brief", "templates", "sizes")
        brand = brand_of(body["brand_id"]) if body.get("brand_id") else None
        if len(body["templates"]) * len(body["sizes"]) > 40:
            raise HTTPException(400, "Max 40 designs per call")
        bg = None
        if body.get("bg_prompt"):
            w0, h0 = size_of(body["sizes"][0])
            bg = b64e(ai("generate_image", provider=body.get("provider"), prompt=body["bg_prompt"], width=w0, height=h0))
        out = []
        for t in body["templates"]:
            for k in body["sizes"]:
                w, h = size_of(k)
                try:
                    layers = S.template_layers(t, w, h, brand, body["brief"].get("headline", ""))
                except KeyError as exc:
                    raise HTTPException(400, str(exc)) from exc
                out.append(st().put("projects", S.new_project(f"{body['brief'].get('name', 'Campaign')} - {t} - {k}", w, h, layers, bg))["id"])
        return {"project_ids": out}

    @r.post("/export/batch")
    def export_batch(body: dict = Body(...)):
        """project_ids[], sizes?[], formats[], dpi?, transparent? -> zip (base64)."""
        need(body, "project_ids")
        sizes, fmts = body.get("sizes") or [None], body.get("formats") or ["PNG"]
        if len(body["project_ids"]) * len(sizes) * len(fmts) > 50:
            raise HTTPException(400, "Max 50 files per call")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for pid in body["project_ids"]:
                p = proj(pid)
                for k in sizes:
                    for f in fmts:
                        tr = bool(body.get("transparent")) and f.upper() == "PNG" and not k
                        img = S.render_project(p, transparent=tr)
                        if k:
                            img = S.resize_to(img, *size_of(k), body.get("mode", "blur_pad"))
                        z.writestr(f"{p['name']}_{k or 'orig'}.{f.lower()}", S.to_bytes(img, f, int(body.get("dpi", 300))))
        return {"zip_base64": b64e(buf.getvalue())}

    # ---- AI editing
    @r.post("/region-edit")
    def region_edit(body: dict = Body(...)):
        """Edit/inpaint/remove inside box [x0,y0,x1,y1] (0-1 fractions); the rest stays untouched."""
        need(body, "image_base64", "box", "prompt")
        img = S.load(b64d(body["image_base64"]))
        x0, y0, x1, y1 = (int(v * s) for v, s in zip(body["box"], (img.width, img.height) * 2))
        if x1 - x0 < 16 or y1 - y0 < 16:
            raise HTTPException(400, "Box too small")
        pad = int(.1 * max(x1 - x0, y1 - y0))
        px0, py0, px1, py1 = max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)
        buf = io.BytesIO()
        img.crop((px0, py0, px1, py1)).save(buf, "PNG")
        edited = Image.open(io.BytesIO(ai("edit_image", provider=body.get("provider"), image_bytes=buf.getvalue(),
                                          prompt=f"{body['prompt']}. Keep everything outside the change identical.")))
        return {"image_base64": b64e(S.to_bytes(S.paste_region(img, edited, (px0, py0, px1, py1)), "PNG"))}

    @r.post("/style-transfer")
    def style_transfer(body: dict = Body(...)):
        need(body, "reference_base64", "prompt")
        data = ai("edit_image", provider=body.get("provider"), image_bytes=b64d(body["reference_base64"]),
                  prompt=f"Use the colours, textures, lighting and mood of this reference image to create a new poster "
                         f"background: {body['prompt']}. Do not copy its subject. No text.")
        return {"image_base64": b64e(data)}

    @r.post("/replace-subject-bg")
    def replace_subject_bg(body: dict = Body(...)):
        """Code-only: cut out the subject then place it on a colour or another image."""
        from .core.extras import remove_background
        need(body, "image_base64")
        cut = Image.open(io.BytesIO(remove_background(b64d(body["image_base64"]), int(body.get("tolerance", 40))))).convert("RGBA")
        bg = (S.cover(S.load(b64d(body["background_base64"])), *cut.size) if body.get("background_base64")
              else Image.new("RGB", cut.size, body.get("color", "#FFFFFF"))).convert("RGBA")
        return {"image_base64": b64e(S.to_bytes(Image.alpha_composite(bg, cut), "PNG"))}

    # ---- text intelligence
    @r.post("/proofread")
    def proofread(body: dict = Body(...)):
        need(body, "texts")
        out = [{"text": t, **S.proofread(t, body.get("lang", "en"))} for t in body["texts"]]
        if body.get("use_ai"):
            for o in out:
                o["ai_suggestion"] = ai("enhance_prompt", provider=body.get("provider"), prompt=o["corrected"],
                                        context="Proofread this poster text. Fix spelling and grammar only. Return only the corrected text.")
        return out

    @r.post("/translate")
    def translate(body: dict = Body(...)):
        need(body, "text", "lang")
        meta = S.LANGUAGES.get(body["lang"])
        if not meta:
            raise HTTPException(400, f"lang must be one of {sorted(S.LANGUAGES)}")
        out = ai("enhance_prompt", provider=body.get("provider"),
                 prompt=f"Translate into {meta['name']}: {body['text']}",
                 context="Return only the translation, no notes.")
        return {"translation": out, "font_available": meta["font"],
                "warning": None if meta["font"] else f"No {meta['name']} font bundled; upload one via /fonts."}

    @r.post("/projects/{pid}/translate")
    def project_translate(pid: str, body: dict = Body(...)):
        """New project copy with Headline/Title/Offer/Subheading text layers translated."""
        need(body, "lang")
        p = proj(pid)
        layers = copy.deepcopy(S.current(p))
        for l in layers:
            if l["type"] == "text" and l.get("name") in ("Headline", "Title", "Offer", "Subheading"):
                l["text"] = translate({"text": l["text"], "lang": body["lang"], "provider": body.get("provider")})["translation"]
        return {"project_id": new_from(p, f"{p['name']} - {body['lang']}", p["width"], p["height"], layers)["id"],
                "font_available": S.LANGUAGES[body["lang"]]["font"]}

    @r.post("/recommend-model")
    def recommend_model(body: dict = Body(default={})):
        """feature (default generate_image), priority quality|speed|cost|balanced."""
        feat, pri = body.get("feature", "generate_image"), body.get("priority", "balanced")
        if pri not in ("quality", "speed", "cost", "balanced"):
            raise HTTPException(400, "priority: quality|speed|cost|balanced")
        cfg = reg().config.get("providers") or {}
        cands = [{"name": n, "cost": (cfg.get(n) or {}).get("cost_per_image")}
                 for n, pr in reg().providers.items() if pr.supports(feat) and n != "mock"]
        return S.recommend(cands, st().leaderboard(), pri)
