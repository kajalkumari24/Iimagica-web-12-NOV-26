"""Pure design logic: sizes/export, layers + renderer, templates, layout/quality
analysis, brand check, festivals, captions, backup. No network, no models."""
from __future__ import annotations

import base64
import copy
import datetime as dt
import io
import math
import os
import time
import uuid
import zipfile

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .colors import contrast_ratio, hex_to_rgb, readable_text_color, rgb_to_hex
from .compose import _font, _font_path, _script

# ---------------------------------------------------------------- sizes/export
SIZES = {
    "instagram_post": (1080, 1350), "instagram_square": (1080, 1080),
    "instagram_story": (1080, 1920), "whatsapp_status": (1080, 1920),
    "facebook_post": (1200, 630), "linkedin_post": (1200, 627),
    "twitter_post": (1600, 900), "youtube_thumbnail": (1280, 720),
    "a4_portrait_300dpi": (2480, 3508), "a4_landscape_300dpi": (3508, 2480),
}


def load(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def to_bytes(img: Image.Image, fmt: str = "PNG", dpi: int = 300, quality: int = 95) -> bytes:
    fmt = {"JPG": "JPEG"}.get(fmt.upper(), fmt.upper())
    if fmt not in ("PNG", "JPEG", "PDF"):
        raise ValueError("format must be PNG, JPG or PDF")
    buf = io.BytesIO()
    if fmt != "PNG" and img.mode == "RGBA":
        flat = Image.new("RGB", img.size, "white")
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    if fmt == "PNG":
        img.save(buf, "PNG", dpi=(dpi, dpi))
    elif fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality, dpi=(dpi, dpi))
    else:
        img.convert("RGB").save(buf, "PDF", resolution=float(dpi))
    return buf.getvalue()


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    l, t = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((l, t, l + w, t + h))


def resize_to(img: Image.Image, w: int, h: int, mode: str = "blur_pad") -> Image.Image:
    """'cover' crops to fill; 'blur_pad' keeps the whole design on a blurred fill."""
    if mode == "cover":
        return cover(img, w, h)
    bg = cover(img, w, h).filter(ImageFilter.GaussianBlur(max(w, h) // 40))
    s = min(w / img.width, h / img.height)
    fg = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


def expand(img: Image.Image, left=0, right=0, top=0, bottom=0) -> Image.Image:
    """Code-only canvas expansion (blurred edge fill). Use /edit for AI outpainting."""
    W, H = img.width + left + right, img.height + top + bottom
    bg = cover(img, W, H).filter(ImageFilter.GaussianBlur(max(W, H) // 30))
    bg.paste(img, (left, top))
    return bg


# --------------------------------------------------------------- layers
def new_layer(**kw) -> dict:
    base = {"id": uuid.uuid4().hex[:8], "type": "text", "name": "", "x": 0, "y": 0,
            "w": 200, "h": 100, "rotation": 0, "opacity": 1.0, "locked": False,
            "visible": True}
    base.update(kw)
    if base["type"] not in ("text", "image", "rect", "ellipse", "polygon", "wave", "frame"):
        raise ValueError("layer type must be text, image, rect, ellipse, polygon, wave or frame")
    return base


def _align(L: list, sel: list, op: dict) -> list:
    if not sel:
        raise KeyError("no layers selected")
    if any(l["locked"] for l in sel):
        raise PermissionError("layer is locked")
    m = op.get("mode", "left")
    if op["op"] == "distribute":
        ax, sz = ("x", "w") if m in ("h", "horizontal") else ("y", "h")
        srt = sorted(sel, key=lambda l: l[ax])
        if len(srt) < 3:
            return L
        gap = ((srt[-1][ax] + srt[-1][sz]) - srt[0][ax] - sum(l[sz] for l in srt)) / (len(srt) - 1)
        pos = srt[0][ax]
        for l in srt:
            l[ax] = round(pos)
            pos += l[sz] + gap
        return L
    if len(sel) > 1:
        x0, y0 = min(l["x"] for l in sel), min(l["y"] for l in sel)
        x1, y1 = max(l["x"] + l["w"] for l in sel), max(l["y"] + l["h"] for l in sel)
    else:
        x0, y0 = 0, 0
        x1, y1 = op.get("canvas") or (sel[0]["x"] + sel[0]["w"], sel[0]["y"] + sel[0]["h"])
    for l in sel:
        if m == "left": l["x"] = x0
        elif m == "right": l["x"] = x1 - l["w"]
        elif m == "center": l["x"] = round(x0 + (x1 - x0 - l["w"]) / 2)
        elif m == "top": l["y"] = y0
        elif m == "bottom": l["y"] = y1 - l["h"]
        elif m == "middle": l["y"] = round(y0 + (y1 - y0 - l["h"]) / 2)
        else: raise ValueError("mode: left|center|right|top|middle|bottom")
    return L


def apply_op(layers: list, op: dict) -> list:
    """add | update | delete | duplicate | reorder | lock | batch | group | ungroup |
    align | distribute | paste. Returns a new list (batch = one undo step)."""
    L = copy.deepcopy(layers)
    kind = op.get("op")
    if kind == "batch":
        for o in op["ops"]:
            L = apply_op(L, {"canvas": op.get("canvas"), **o})
        return L
    if kind == "add":
        L.append(new_layer(**op["layer"]))
        return L
    if kind == "paste":
        for src in op["layers"]:
            c = {k: v for k, v in src.items() if k != "id"}
            c.update(x=c.get("x", 0) + 20, y=c.get("y", 0) + 20, locked=False)
            L.append(new_layer(**c))
        return L
    if kind in ("group", "ungroup", "align", "distribute"):
        sel = [l for l in L if l["id"] in (op.get("ids") or [])]
        if kind == "group":
            g = uuid.uuid4().hex[:6]
            for l in sel:
                l["group"] = g
        elif kind == "ungroup":
            for l in sel:
                l.pop("group", None)
        else:
            return _align(L, sel, op)
        return L
    idx = next((i for i, l in enumerate(L) if l["id"] == op.get("id")), None)
    if idx is None:
        raise KeyError(f"layer {op.get('id')} not found")
    if kind == "lock":
        L[idx]["locked"] = bool(op.get("locked", True))
    elif L[idx]["locked"] and kind in ("update", "delete", "reorder"):
        raise PermissionError("layer is locked")
    elif kind == "update":
        L[idx].update({k: v for k, v in op["changes"].items() if k != "id"})
    elif kind == "delete":
        L.pop(idx)
    elif kind == "duplicate":
        c = copy.deepcopy(L[idx])
        c.update(id=uuid.uuid4().hex[:8], x=c["x"] + 20, y=c["y"] + 20, locked=False,
                 name=(c["name"] + " copy").strip())
        L.insert(idx + 1, c)
    elif kind == "reorder":
        l = L.pop(idx)
        L.insert(max(0, min(len(L), int(op["index"]))), l)
    else:
        raise ValueError(f"unknown op {kind!r}")
    return L


def _rgba(hexv: str, a: int = 255):
    r, g, b = hex_to_rgb(hexv)
    return (r, g, b, a)


def _wrap(d, text, font, width):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if cur and d.textlength(t, font=font) > width:
                lines.append(cur)
                cur = word
            else:
                cur = t
        lines.append(cur)
    return lines


USER_FONT_DIR: str | None = None


def font_for(L: dict, size: int, text: str):
    """Layer font: user-uploaded or bundled file by name, else the default fonts."""
    n = os.path.basename(str(L.get("font") or ""))
    for p in ((USER_FONT_DIR and os.path.join(USER_FONT_DIR, n)), _font_path(n)):
        if n and p and os.path.isfile(p):
            try:
                return ImageFont.truetype(p, int(size))
            except OSError:
                pass
    return _font(size, bool(L.get("bold")), _script(text))


def render(width: int, height: int, layers: list, bg: Image.Image | None = None,
           transparent: bool = False) -> Image.Image:
    if bg:
        canvas = cover(bg, width, height).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    for L in layers:
        if not L.get("visible", True):
            continue
        lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        a = int(255 * float(L.get("opacity", 1)))
        x, y, w, h = (int(L.get(k, 0)) for k in ("x", "y", "w", "h"))
        t = L["type"]
        stroke = _rgba(L["stroke"], a) if L.get("stroke") else None
        sw = int(L.get("stroke_width", 0)) if stroke else 0
        if t == "rect":
            d.rounded_rectangle((x, y, x + w, y + h), radius=int(L.get("radius", 0)),
                                fill=_rgba(L.get("fill", "#000000"), a), outline=stroke, width=sw)
        elif t == "ellipse":
            d.ellipse((x, y, x + w, y + h), fill=_rgba(L.get("fill", "#000000"), a),
                      outline=stroke, width=sw)
        elif t == "polygon":
            pts = [(x + px * w, y + py * h) for px, py in L.get("points", [[0, 0], [1, 0], [1, 1], [0, 1]])]
            d.polygon(pts, fill=_rgba(L.get("fill", "#000000"), a), outline=stroke)
        elif t == "wave":
            amp, cyc, ph = float(L.get("amplitude", .15)) * h, float(L.get("cycles", 1.5)), float(L.get("phase", 0))
            top = [(x + i * w / 60, y + amp + amp * math.sin(2 * math.pi * cyc * i / 60 + ph)) for i in range(61)]
            d.polygon(top + [(x + w, y + h), (x, y + h)], fill=_rgba(L.get("fill", "#000000"), a))
        elif t == "frame":
            d.rounded_rectangle((x, y, x + w, y + h), radius=int(L.get("radius", 0)),
                                outline=_rgba(L.get("stroke", "#FFFFFF"), a),
                                width=max(1, int(L.get("stroke_width", 8))))
        elif t == "image" and L.get("src_base64"):
            im = Image.open(io.BytesIO(base64.b64decode(L["src_base64"]))).convert("RGBA")
            im = im.resize((max(1, w), max(1, h)), Image.LANCZOS)
            if L.get("mask"):
                mk = Image.new("L", im.size, 0)
                md = ImageDraw.Draw(mk)
                box = (0, 0, im.width - 1, im.height - 1)
                if L["mask"] in ("circle", "ellipse"):
                    md.ellipse(box, fill=255)
                else:
                    md.rounded_rectangle(box, radius=int(L.get("radius", 30)), fill=255)
                im.putalpha(ImageChops.multiply(im.getchannel("A"), mk))
            if a < 255:
                im.putalpha(im.getchannel("A").point(lambda v: v * a // 255))
            lay.paste(im, (x, y), im)
        elif t == "text":
            text = str(L.get("text", ""))
            size = int(L.get("font_size", 48))
            font = font_for(L, size, text)
            lines = _wrap(d, text, font, w)
            lh = size * float(L.get("line_spacing", 1.2))
            fill = _rgba(L.get("color", "#000000"), a)
            for i, line in enumerate(lines):
                tw = d.textlength(line, font=font)
                off = {"center": (w - tw) / 2, "right": w - tw}.get(L.get("align", "left"), 0)
                pos = (x + off, y + i * lh)
                if L.get("shadow"):
                    d.text((pos[0] + 3, pos[1] + 3), line, font=font, fill=(0, 0, 0, a // 2))
                d.text(pos, line, font=font, fill=fill,
                       stroke_width=sw, stroke_fill=stroke or fill)
        if L.get("rotation"):
            lay = lay.rotate(-float(L["rotation"]), center=(x + w / 2, y + h / 2))
        canvas = Image.alpha_composite(canvas, lay)
    return canvas if transparent else canvas.convert("RGB")


def template_layers(name: str, w: int, h: int, brand: dict | None = None, text: str = "") -> list:
    b = brand or {}
    cols = b.get("colors") or ["#C2185B", "#FFC107"]
    p, s = cols[0], cols[1 if len(cols) > 1 else 0]
    nm = b.get("name", "Your Business")
    T = lambda **k: new_layer(type="text", **k)
    R = lambda **k: new_layer(type="rect", **k)
    if name == "festival_greeting":
        return [T(name="Headline", text=text or "Happy Festival", x=int(w * .08), y=int(h * .08),
                  w=int(w * .84), h=int(h * .2), font_size=int(w * .09), bold=True,
                  align="center", color="#FFFFFF", shadow=True),
                R(name="Footer bar", x=0, y=int(h * .9), w=w, h=int(h * .1), fill=p, footer=True),
                T(name="Business", text=nm, x=int(w * .05), y=int(h * .92), w=int(w * .9),
                  h=int(h * .06), font_size=int(w * .035), bold=True, color="#FFFFFF", align="center", footer=True)]
    if name == "offer_sale":
        return [R(name="Badge", x=int(w * .06), y=int(h * .06), w=int(w * .5), h=int(h * .1),
                  fill=s, radius=int(w * .02)),
                T(name="Offer", text=text or "FLAT 50% OFF", x=int(w * .08), y=int(h * .075),
                  w=int(w * .46), h=int(h * .08), font_size=int(w * .05), bold=True, color="#000000"),
                T(name="Business", text=nm, x=int(w * .06), y=int(h * .88), w=int(w * .88),
                  h=int(h * .08), font_size=int(w * .045), bold=True, color=p, shadow=True)]
    if name == "event_invite":
        return [T(name="Title", text=text or "You're Invited", x=int(w * .1), y=int(h * .35),
                  w=int(w * .8), h=int(h * .2), font_size=int(w * .08), bold=True,
                  align="center", color=p, shadow=True),
                new_layer(type="ellipse", name="Accent", x=int(w * .4), y=int(h * .6),
                          w=int(w * .2), h=int(w * .2), fill=s, opacity=.8)]
    if name == "minimal_brand":
        return [T(name="Headline", text=text or nm, x=int(w * .1), y=int(h * .42), w=int(w * .8),
                  h=int(h * .16), font_size=int(w * .07), bold=True, align="center", color=p),
                R(name="Rule", x=int(w * .35), y=int(h * .6), w=int(w * .3), h=6, fill=s)]
    raise KeyError(f"unknown template {name!r}")


TEMPLATES = ["festival_greeting", "offer_sale", "event_invite", "minimal_brand"]

# ------------------------------------------------ analysis (layout, quality, brand)
def text_regions(img: Image.Image) -> list:
    """Candidate text areas ranked calmest first, with a readable text colour."""
    g = np.asarray(img.convert("L").resize((96, 96)), float)
    gy, gx = np.gradient(g)
    e = np.hypot(gx, gy)
    rgb = np.asarray(img.resize((96, 96)), float)
    regions = {"top": (0, 0, 1, .25), "bottom": (0, .75, 1, 1), "left": (0, .25, .4, .75),
               "right": (.6, .25, 1, .75), "center": (.2, .35, .8, .65)}
    out = []
    for n, (x0, y0, x1, y1) in regions.items():
        sl = (slice(int(y0 * 96), int(y1 * 96)), slice(int(x0 * 96), int(x1 * 96)))
        mean = tuple(int(v) for v in rgb[sl].reshape(-1, 3).mean(0))
        wh, bl = contrast_ratio(mean, (255, 255, 255)), contrast_ratio(mean, (0, 0, 0))
        out.append({"region": n, "box": [x0, y0, x1, y1], "busyness": round(float(e[sl].mean()), 2),
                    "text_color": "#ffffff" if wh >= bl else "#000000",
                    "contrast": round(max(wh, bl), 2)})
    return sorted(out, key=lambda r: r["busyness"])


def evaluate(img: Image.Image) -> dict:
    """Heuristic design-quality score 0-100 (not an AI judgement)."""
    best = text_regions(img)[0]
    g = np.asarray(img.convert("L").resize((256, 256)), float)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    a = np.asarray(img.resize((128, 128)), float)
    rg, yb = a[:, :, 0] - a[:, :, 1], .5 * (a[:, :, 0] + a[:, :, 1]) - a[:, :, 2]
    gy, gx = np.gradient(g)
    e = np.hypot(gx, gy)
    ys, xs = np.indices(e.shape)
    tot = e.sum() or 1.0
    cx, cy = (e * xs).sum() / tot / e.shape[1], (e * ys).sum() / tot / e.shape[0]
    clip = lambda v: float(max(0.0, min(1.0, v)))
    parts = {"text_space": clip(1 - best["busyness"] / 25),
             "text_contrast": clip((best["contrast"] - 1) / 6),
             "sharpness": clip(float(lap.var()) / 300),
             "colourfulness": clip(math.hypot(rg.std(), yb.std()) / 60),
             "balance": clip(1 - math.hypot(cx - .5, cy - .5) / .35)}
    wts = {"text_space": .25, "text_contrast": .2, "sharpness": .2, "colourfulness": .15, "balance": .2}
    return {"score": round(100 * sum(parts[k] * wts[k] for k in parts), 1),
            "parts": {k: round(v, 2) for k, v in parts.items()},
            "best_text_region": best, "method": "heuristic"}


def brand_check(img: Image.Image, brand_colors: list, tol: float = 60, min_coverage: float = .05) -> dict:
    q = np.asarray(img.resize((128, 128)), float).reshape(-1, 3)
    per = {}
    for c in brand_colors:
        per[c] = round(float((np.linalg.norm(q - np.array(hex_to_rgb(c), float), axis=1) < tol).mean()), 3)
    total = round(sum(per.values()), 3)
    return {"per_colour_coverage": per, "total_coverage": total,
            "pass": total >= min_coverage,
            "advice": "Brand colours are visible." if total >= min_coverage else
            "Brand colours barely appear; use them in the footer, headline or frame."}

# ---------------------------------------------------------------- festivals
# (name, hindi, month, day, regions). day=None -> date varies yearly (lunar/solar calendars).
_F = [
    ("New Year", "नया साल", 1, 1, "all"), ("Lohri", "लोहड़ी", 1, 13, "PB,HR,DL"),
    ("Makar Sankranti", "मकर संक्रांति", 1, 14, "all"), ("Pongal", "पोंगल", 1, 14, "TN"),
    ("Republic Day", "गणतंत्र दिवस", 1, 26, "all"), ("Valentine's Day", None, 2, 14, "all"),
    ("Ambedkar Jayanti", None, 4, 14, "all"), ("Labour Day", None, 5, 1, "all"),
    ("Independence Day", "स्वतंत्रता दिवस", 8, 15, "all"), ("Teachers' Day", "शिक्षक दिवस", 9, 5, "all"),
    ("Gandhi Jayanti", "गांधी जयंती", 10, 2, "all"), ("Children's Day", "बाल दिवस", 11, 14, "all"),
    ("Christmas", "क्रिसमस", 12, 25, "all"),
    ("Maha Shivaratri", "महाशिवरात्रि", [2, 3], None, "all"), ("Holi", "होली", [3], None, "all"),
    ("Ugadi", None, [3, 4], None, "KA,AP,TS"), ("Gudi Padwa", None, [3, 4], None, "MH"),
    ("Ram Navami", "राम नवमी", [3, 4], None, "all"), ("Eid al-Fitr", "ईद", [3, 4], None, "all"),
    ("Baisakhi", None, [4], None, "PB,HR"), ("Bihu", None, [4, 1, 10], None, "AS"),
    ("Vishu", None, [4], None, "KL"), ("Buddha Purnima", "बुद्ध पूर्णिमा", [5], None, "all"),
    ("Eid al-Adha", None, [5, 6, 7], None, "all"), ("Raksha Bandhan", "रक्षाबंधन", [8], None, "all"),
    ("Janmashtami", "जन्माष्टमी", [8, 9], None, "all"), ("Ganesh Chaturthi", "गणेश चतुर्थी", [8, 9], None, "all"),
    ("Onam", None, [8, 9], None, "KL"), ("Durga Puja", None, [9, 10], None, "WB,AS,OD"),
    ("Navratri", "नवरात्रि", [9, 10], None, "all"), ("Dussehra", "दशहरा", [10], None, "all"),
    ("Karwa Chauth", "करवा चौथ", [10, 11], None, "all"), ("Diwali", "दिवाली", [10, 11], None, "all"),
    ("Bhai Dooj", "भाई दूज", [10, 11], None, "all"), ("Chhath Puja", "छठ पूजा", [11], None, "BR,JH,UP"),
    ("Guru Nanak Jayanti", "गुरु नानक जयंती", [11], None, "all"),
]


def festivals(today: dt.date | None = None, days: int = 45, region: str | None = None) -> list:
    """Upcoming festivals. Fixed-date ones get days_left; movable ones get
    date_varies=True (check the year's calendar before publishing)."""
    today = today or dt.date.today()
    out = []
    for name, hi, month, day, regions in _F:
        if region and regions != "all" and region.upper() not in regions.split(","):
            continue
        rec = {"name": name, "name_hi": hi, "regions": regions}
        if day:
            d = dt.date(today.year, month, day)
            if d < today:
                d = dt.date(today.year + 1, month, day)
            rec.update(date=d.isoformat(), days_left=(d - today).days, date_varies=False)
            if rec["days_left"] <= days:
                out.append(rec)
        else:
            months = month
            nxt = (today.month % 12) + 1
            if today.month in months or (days > 15 and nxt in months):
                rec.update(date=None, days_left=None, date_varies=True, months=months)
                out.append(rec)
    return sorted(out, key=lambda r: (r["days_left"] is None, r["days_left"] or 0))


LANGUAGES = {"en": {"name": "English", "font": True}, "hi": {"name": "Hindi", "font": True},
             "mr": {"name": "Marathi", "font": True}, "ta": {"name": "Tamil", "font": False},
             "te": {"name": "Telugu", "font": False}, "bn": {"name": "Bengali", "font": False},
             "gu": {"name": "Gujarati", "font": False}, "pa": {"name": "Punjabi", "font": False}}


def greeting(festival: str, lang: str = "en") -> str:
    f = next((x for x in _F if x[0].lower() == festival.lower()), None)
    hi = f[1] if f else None
    if lang == "hi" and hi:
        return f"{hi} की हार्दिक शुभकामनाएँ"
    if lang == "mr" and hi:
        return f"{hi} च्या हार्दिक शुभेच्छा"
    return f"Happy {festival}!"


def suggestions(today=None, region=None, days: int = 30) -> list:
    out = []
    for f in festivals(today, days, region):
        out.append({**f, "greeting_en": greeting(f["name"]),
                    "suggested_prompt": f"{f['name']} festive poster background, warm "
                                        f"celebratory colours, space for headline and footer"})
    return out


def captions(occasion: str, business: str = "", tone: str = "friendly", lang: str = "en",
             cta: str = "") -> list:
    tags = " ".join(f"#{''.join(c for c in w if c.isalnum())}" for w in
                    (occasion.title().replace(" ", ""), business.title().replace(" ", ""), "Festival")
                    if w)
    g = greeting(occasion, lang)
    by = f" from {business}" if business else ""
    tpl = {"friendly": [f"{g} Wishing you joy and prosperity{by}. {cta}",
                        f"{g} May this {occasion} bring happiness to you and your family{by}. {cta}",
                        f"Celebrate {occasion} with us{by}! {cta}"],
           "formal": [f"{g} Warm greetings{by} on the occasion of {occasion}. {cta}",
                      f"On this {occasion}, we extend our best wishes{by}. {cta}"],
           "promo": [f"{g} Special {occasion} offers{by}! {cta or 'Visit us today.'}",
                     f"{occasion} celebration deals{by} — limited time only. {cta}"]}
    return [f"{t.strip()}\n{tags}" for t in tpl.get(tone, tpl["friendly"])]

# ------------------------------------------------------------ backup / restore
def backup(root: str) -> str:
    bdir = os.path.join(root, "backups")
    os.makedirs(bdir, exist_ok=True)
    path = os.path.join(bdir, f"backup-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d != "backups"]
            for f in fn:
                full = os.path.join(dp, f)
                z.write(full, os.path.relpath(full, root))
    return path


def restore(root: str, name: str) -> int:
    path = os.path.join(root, "backups", os.path.basename(name))
    if not os.path.isfile(path):
        raise FileNotFoundError(name)
    with zipfile.ZipFile(path) as z:
        z.extractall(root)  # extractall strips absolute/.. paths
        return len(z.namelist())


# ------------------------------------------------- projects (autosave/undo/redo)
def new_project(name: str, w: int, h: int, layers: list, bg_base64: str | None = None) -> dict:
    return {"id": uuid.uuid4().hex[:10], "name": name, "width": w, "height": h,
            "bg_base64": bg_base64, "versions": [layers], "cursor": 0, "favorite": False,
            "created": time.time(), "updated": time.time()}


def current(p: dict) -> list:
    return p["versions"][p["cursor"]]


def commit(p: dict, layers: list, cap: int = 50) -> dict:
    """Every change is an autosaved version; redo history is dropped."""
    v = p["versions"][: p["cursor"] + 1] + [layers]
    p["versions"] = v[-cap:]
    p["cursor"] = len(p["versions"]) - 1
    p["updated"] = time.time()
    return p


def undo(p: dict) -> dict:
    p["cursor"] = max(0, p["cursor"] - 1)
    return p


def redo(p: dict) -> dict:
    p["cursor"] = min(len(p["versions"]) - 1, p["cursor"] + 1)
    return p


def render_project(p: dict, transparent: bool = False) -> Image.Image:
    bg = load(base64.b64decode(p["bg_base64"])) if p.get("bg_base64") else None
    return render(p["width"], p["height"], current(p), bg, transparent)


# ----------------------------------------------- resize, footer, brand, region edit
def scale_layers(layers: list, sx: float, sy: float) -> list:
    """Re-layout a design for another canvas size (positions, sizes and fonts scale)."""
    out, k = copy.deepcopy(layers), min(sx, sy)
    for l in out:
        l["x"], l["w"] = round(l["x"] * sx), round(l["w"] * sx)
        l["y"], l["h"] = round(l["y"] * sy), round(l["h"] * sy)
        for key in ("font_size", "stroke_width", "radius"):
            if key in l:
                l[key] = max(1, round(l[key] * k))
    return out


def footer_layers(layout: str, w: int, h: int, contacts: dict, colors: list,
                  style: str = "solid", font: str | None = None) -> list:
    """Footer/frame as layers. layout: bottom|top|left|right|full; style: solid|wave|ribbon|glass|frame."""
    box = {"bottom": (0, .88, 1, .12), "top": (0, 0, 1, .12), "full": (0, .8, 1, .2),
           "left": (0, 0, .24, 1), "right": (.76, 0, .24, 1)}.get(layout)
    if box is None:
        raise ValueError("layout: bottom|top|left|right|full")
    bx, by, bw, bh = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
    p = colors[0] if colors else "#B71C1C"
    s2 = colors[1] if len(colors) > 1 else "#FFC107"
    tcol = rgb_to_hex(readable_text_color(hex_to_rgb(p)))
    tag = {"footer": True}
    out = []
    if style == "wave":
        amp = .18
        out.append(new_layer(type="wave", name="Footer wave", x=bx, y=by - int(bh * amp * 2), w=bw,
                             h=bh + int(bh * amp * 2), amplitude=amp, fill=p, **tag))
    elif style == "ribbon":
        out.append(new_layer(type="polygon", name="Footer ribbon", x=bx, y=by, w=bw, h=bh, fill=p,
                             points=[[0, 0], [1, 0], [.97, .5], [1, 1], [0, 1], [.03, .5]], **tag))
    elif style == "glass":
        out.append(new_layer(type="rect", name="Footer glass", x=bx, y=by, w=bw, h=bh, fill=p,
                             opacity=.6, stroke="#FFFFFF", stroke_width=2, **tag))
    else:
        out.append(new_layer(type="rect", name="Footer bar", x=bx, y=by, w=bw, h=bh, fill=p, **tag))
        if style == "frame":
            out.append(new_layer(type="frame", name="Frame", x=10, y=10, w=w - 20, h=h - 20,
                                 stroke=s2, stroke_width=max(4, w // 90), radius=20, **tag))
    out.append(new_layer(type="rect", name="Footer accent", x=bx, y=by, w=bw if bh < bw else 6,
                         h=6 if bh < bw else bh, fill=s2, **tag))
    lines = [contacts.get(k) for k in ("phone", "whatsapp", "email", "website", "address") if contacts.get(k)]
    if contacts.get("name"):
        lines.insert(0, contacts["name"])
    if lines:
        horiz = bw > bh
        text = "   •   ".join(lines[:3]) + ("\n" + "   •   ".join(lines[3:]) if horiz and lines[3:] else "")
        text = text if horiz else "\n".join(lines)
        size = int(bh * (.26 if len(lines) <= 3 else .2)) if horiz else int(bw * .11)
        out.append(new_layer(type="text", name="Footer contacts", text=text, x=bx + int(w * .03),
                             y=by + int(bh * .18) if horiz else int(h * .06), w=bw - int(w * .06),
                             h=int(bh * .7) if horiz else int(h * .88), font_size=max(10, size),
                             bold=True, color=tcol, align="center", **({"font": font} if font else {}), **tag))
    return out


def logo_spot(img: Image.Image, lw: int, lh: int, margin: int = 24) -> tuple:
    """Calmest corner (lowest edge energy) for a logo of lw x lh pixels."""
    W, H = img.size
    g = np.asarray(img.convert("L"), float)
    gy, gx = np.gradient(g)
    e = np.hypot(gx, gy)
    best = None
    for x, y in ((margin, margin), (W - lw - margin, margin), (margin, H - lh - margin),
                 (W - lw - margin, H - lh - margin)):
        x, y = max(0, x), max(0, y)
        v = float(e[y:y + lh, x:x + lw].mean()) if e[y:y + lh, x:x + lw].size else 1e9
        if best is None or v < best[0]:
            best = (v, x, y)
    return best[1], best[2]


def apply_brand(layers: list, w: int, h: int, brand: dict, base: Image.Image | None = None) -> list:
    """One-click brand kit: colours, font and an auto-placed logo."""
    cols = brand.get("colors") or []
    p = cols[0] if cols else None
    s2 = cols[1] if len(cols) > 1 else p
    out = [l for l in copy.deepcopy(layers) if l.get("name") != "Logo"]
    for l in out:
        if l["type"] in ("rect", "ellipse", "polygon", "wave") and p:
            l["fill"] = p if l.get("footer") else s2
        if l["type"] == "text":
            if brand.get("font"):
                l["font"] = brand["font"]
            if l.get("footer") and p:
                l["color"] = rgb_to_hex(readable_text_color(hex_to_rgb(p)))
    if brand.get("logo_base64"):
        lg = Image.open(io.BytesIO(base64.b64decode(brand["logo_base64"])))
        lw = int(w * .16)
        lh = max(1, round(lw * lg.height / lg.width))
        x, y = logo_spot(base if base is not None else render(w, h, out), lw, lh)
        out.append(new_layer(type="image", name="Logo", x=x, y=y, w=lw, h=lh,
                             src_base64=brand["logo_base64"]))
    return out


def paste_region(base: Image.Image, edited: Image.Image, box: tuple, feather: int = 12) -> Image.Image:
    """Paste an edited crop back with a feathered edge so the rest stays untouched."""
    x0, y0, x1, y1 = box
    out = base.convert("RGB").copy()
    patch = edited.convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).rectangle((feather, feather, patch.width - feather, patch.height - feather), fill=255)
    out.paste(patch, (x0, y0), mask.filter(ImageFilter.GaussianBlur(feather / 2)))
    return out

# --------------------------------------------------- proofreading, model advice
_TYPOS = {"teh": "the", "recieve": "receive", "occassion": "occasion", "wich": "which",
          "definately": "definitely", "seperate": "separate", "adress": "address", "wishs": "wishes"}


def proofread(text: str, lang: str = "en") -> dict:
    """Rule-based checks (spacing, repeats, punctuation, common typos). Not a full grammar checker."""
    import re
    issues, fixed = [], text
    def fix(pattern, repl, msg, flags=0):
        nonlocal fixed
        if re.search(pattern, fixed, flags):
            issues.append(msg)
            fixed = re.sub(pattern, repl, fixed, flags=flags)
    fix(r"[ \t]{2,}", " ", "Multiple spaces")
    fix(r"\b(\w+)\s+\1\b", r"\1", "Repeated word", re.I)
    fix(r"\s+([,.!?;:।])", r"\1", "Space before punctuation")
    fix(r"([,.!?;:])(?=[^\s\d\"')\]])", r"\1 ", "Missing space after punctuation")
    if lang == "en":
        for bad, good in _TYPOS.items():
            fix(rf"\b{bad}\b", good, f"Typo: {bad} -> {good}", re.I)
        fix(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), "Sentence should start with a capital")
    return {"issues": issues, "corrected": fixed.strip(), "ok": not issues, "method": "rules"}


def recommend(cands: list, board: list, priority: str = "balanced") -> list:
    """cands: [{name, cost}] already filtered by capability. Ranks using benchmark history."""
    W = {"quality": (.6, .2, .1, .1), "speed": (.15, .2, .55, .1), "cost": (.15, .2, .1, .55),
         "balanced": (.35, .25, .2, .2)}[priority]
    by = {b["provider"]: b for b in board}
    ms = [b["avg_ms"] for b in board if b.get("avg_ms")]
    costs = [c["cost"] for c in cands if c.get("cost")]
    out = []
    for c in cands:
        b = by.get(c["name"], {})
        q = (b["overall"] / 5) if b.get("overall") else .5
        r = b.get("success_rate", .5)
        sp = (min(ms) / b["avg_ms"]) if b.get("avg_ms") and ms else .5
        co = (min(costs) / c["cost"]) if c.get("cost") and costs else .5
        score = W[0] * q + W[1] * r + W[2] * sp + W[3] * co
        out.append({"provider": c["name"], "score": round(score, 3),
                    "has_benchmark_data": bool(b), "cost_per_image": c.get("cost")})
    return sorted(out, key=lambda x: -x["score"])
