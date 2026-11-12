"""Design checks and auto-fixes, Indian formats/print sizes/business presets, upload safety, duplicate finder."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import os
import re
from decimal import Decimal

from PIL import Image

from . import studio as S

MM = 300 / 25.4
mm = lambda v: round(v * MM)  # noqa: E731  millimetres -> pixels at 300 dpi
PRINT_SIZES = {
    "a3_portrait_300dpi": (mm(297), mm(420)), "a5_portrait_300dpi": (mm(148), mm(210)),
    "a6_portrait_300dpi": (mm(105), mm(148)), "dl_flyer_300dpi": (mm(99), mm(210)),
    "visiting_card_90x50mm_300dpi": (mm(90), mm(50)), "poster_12x18in_300dpi": (3600, 5400),
}
S.SIZES.update(PRINT_SIZES)  # resize/convert/export pick these up automatically

# ------------------------------------------------------------------ design checks
def hex_rgb(h: str):
    h = h.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h[:6]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c):
    c /= 255
    return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4


def ratio(a, b):
    la, lb = (.2126 * _lin(c[0]) + .7152 * _lin(c[1]) + .0722 * _lin(c[2]) for c in (a, b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + .05) / (lo + .05)


def _box(l):
    return tuple(int(l.get(k, 0)) for k in ("x", "y", "w", "h"))


def _bg(p):
    return S.load(base64.b64decode(p["bg_base64"])) if p.get("bg_base64") else None


def check_design(p, margin_pct=3.0, bleed_mm=0.0, min_ratio=4.5):
    w, h = p["width"], p["height"]
    layers = [l for l in S.current(p) if l.get("visible", True)]
    out = []

    def add(kind, sev, ids, msg, **x):
        out.append({"kind": kind, "severity": sev, "layers": ids, "message": msg, **x})

    m = round(min(w, h) * margin_pct / 100) + (mm(bleed_mm) if bleed_mm else 0)
    content = [l for l in layers if l["type"] in ("text", "image")]
    for l in content:
        x, y, lw, lh = _box(l)
        if x < m or y < m or x + lw > w - m or y + lh > h - m:
            add("safe_margin", "warn", [l["id"]], f"'{l.get('name') or l['type']}' is inside the {m}px safe margin.", margin=m)
    texts = [l for l in layers if l["type"] == "text" and str(l.get("text", "")).strip()]
    if texts:
        base = S.render(w, h, [l for l in layers if l["type"] != "text"], _bg(p)).convert("RGB")
        for l in texts:
            x, y, lw, lh = _box(l)
            box = (max(0, x), max(0, y), min(w, x + lw), min(h, y + lh))
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            cells = list(base.crop(box).resize((3, 3), Image.BOX).getdata())
            try:
                fg = hex_rgb(l.get("color", "#000000"))
            except ValueError:
                continue
            worst = min(ratio(fg, c) for c in cells)
            need = 3.0 if int(l.get("font_size", 48)) >= 48 else min_ratio  # large text needs less
            if worst < need:
                best = max(("#FFFFFF", "#000000"), key=lambda c: min(ratio(hex_rgb(c), cc) for cc in cells))
                add("contrast", "error", [l["id"]], f"Text contrast is {worst:.1f}:1; it needs {need}:1.", suggested_color=best)
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            ax, ay, aw, ah = _box(a)
            bx, by, bw, bh = _box(b)
            iw, ih = min(ax + aw, bx + bw) - max(ax, bx), min(ay + ah, by + bh) - max(ay, by)
            f = max(0, iw) * max(0, ih) / max(1, min(aw * ah, bw * bh))
            if f > .15 and not (a.get("group") and a.get("group") == b.get("group")):
                add("overlap", "warn", [a["id"], b["id"]], f"Two text layers overlap by {f:.0%}.")
    for a, b in zip(*(lambda s: (s, s[1:]))(sorted(content, key=lambda l: _box(l)[0]))):
        d = _box(b)[0] - _box(a)[0]
        if 0 < d <= 6:
            add("alignment", "info", [a["id"], b["id"]], f"Left edges differ by {d}px.", snap_x=_box(a)[0])
    for l in layers:
        if l["type"] == "image" and l.get("src_base64"):
            f = int(l.get("w", 0)) / max(1, Image.open(io.BytesIO(base64.b64decode(l["src_base64"]))).width)
            if f > 2:
                add("low_resolution", "warn", [l["id"]], f"Image is enlarged {f:.1f}x and may look soft in print.", enlarge=round(f, 1))
    if p.get("bg_base64"):
        f = w / max(1, Image.open(io.BytesIO(base64.b64decode(p["bg_base64"]))).width)
        if f > 2:
            add("low_resolution", "warn", [], f"Background is enlarged {f:.1f}x and may look soft in print.", enlarge=round(f, 1))
    area = sum(_box(l)[2] * _box(l)[3] for l in content)
    if area:
        cx = sum((_box(l)[0] + _box(l)[2] / 2) * _box(l)[2] * _box(l)[3] for l in content) / area
        cy = sum((_box(l)[1] + _box(l)[3] / 2) * _box(l)[2] * _box(l)[3] for l in content) / area
        if abs(cx - w / 2) / w > .15:
            add("balance", "info", [], f"Content is weighted to the {'right' if cx > w / 2 else 'left'}.")
        if abs(cy - h / 2) / h > .2:
            add("balance", "info", [], f"Content is weighted to the {'bottom' if cy > h / 2 else 'top'}.")
    n = lambda s: sum(i["severity"] == s for i in out)  # noqa: E731
    return {"issues": out, "counts": {s: n(s) for s in ("error", "warn", "info")}, "margin_px": m,
            "score": max(0, 100 - 15 * n("error") - 6 * n("warn") - 2 * n("info"))}


def auto_fix(p, **kw):
    """Safe fixes only: contrast colour, keep inside margins, snap near-aligned edges. Skips locked layers."""
    layers = copy.deepcopy(S.current(p))
    byid, applied, w, h = {l["id"]: l for l in layers}, [], p["width"], p["height"]
    for i in check_design(p, **kw)["issues"]:
        L = byid.get(i["layers"][-1]) if i["layers"] else None
        if not L or L.get("locked"):
            continue
        if i["kind"] == "contrast":
            L["color"] = i["suggested_color"]
        elif i["kind"] == "safe_margin":
            m, lw, lh = i["margin"], max(1, int(L["w"])), max(1, int(L["h"]))
            s = min(1, (w - 2 * m) / lw, (h - 2 * m) / lh)
            L["w"], L["h"] = int(lw * s), int(lh * s)
            L["x"] = min(max(int(L["x"]), m), w - m - L["w"])
            L["y"] = min(max(int(L["y"]), m), h - m - L["h"])
        elif i["kind"] == "alignment":
            L["x"] = i["snap_x"]
        else:
            continue
        applied.append({"kind": i["kind"], "layer": L["id"]})
    return layers, applied

# ------------------------------------------------------------------ Indian formats and presets
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DEV = str.maketrans("0123456789", "०१२३४५६७८९")


def inr(amount, symbol="₹") -> str:
    a = Decimal(str(amount))
    neg, a = a < 0, abs(a)
    s = f"{a:.{0 if a == a.to_integral() else 2}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        whole = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", whole[:-3]) + "," + whole[-3:]
    return ("-" if neg else "") + symbol + whole + ("." + frac if frac else "")


def indian_date(d, lang="en") -> str:
    return f"{d.day} {(HI_MONTHS if lang == 'hi' else EN_MONTHS)[d.month - 1]} {d.year}"


VERIFIED_DATES = [  # Gazetted/central-list based; moon-dependent dates are tentative. Always re-check before publishing.
    {"festival": "Eid al-Fitr", "date": "2027-03-10", "tentative": True, "source": "https://calendarific.com/holidays/2027/IN"},
    {"festival": "Raksha Bandhan", "date": "2027-08-17", "tentative": False, "source": "https://www.staffnews.in/?p=167637"},
    {"festival": "Diwali", "date": "2027-10-29", "tentative": False, "source": "https://happyfares.in/blog/long-weekends-2027-india-leave-planner/"},
]


def _cat(name, pal, h_en, h_hi, s_en, s_hi, size="instagram_post", tip=""):
    return {"name": name, "palette": pal, "headline": {"en": h_en, "hi": h_hi}, "sub": {"en": s_en, "hi": s_hi},
            "size": size, "tip": tip}


BUSINESS = {
    "sweet_shop": _cat("Sweet shop", ["#FFF4E0", "#C2410C", "#3B1D0A"], "Fresh Mithai, Made Daily", "ताज़ी मिठाई, रोज़ बनी", "Order for festivals and family functions", "त्योहार और समारोह के लिए ऑर्डर करें", tip="Post 7-10 days before a festival."),
    "jewellery": _cat("Jewellery", ["#1B1B3A", "#E3B04B", "#FFFFFF"], "Timeless Gold, Honest Prices", "शुद्ध सोना, ईमानदार दाम", "Visit our showroom", "हमारे शोरूम पधारें", tip="Dark backgrounds make gold read as premium."),
    "grocery": _cat("Grocery / kirana", ["#F1FAEE", "#2D6A4F", "#1B2A1F"], "Fresh Groceries, Home Delivered", "ताज़ा किराना, घर तक डिलीवरी", "Order on WhatsApp", "व्हाट्सऐप पर ऑर्डर करें", "whatsapp_status", "Put your WhatsApp number in the footer."),
    "salon": _cat("Salon", ["#FFF0F5", "#B83280", "#2D1B2E"], "Look Your Best", "निखरिए, अपने अंदाज़ में", "Book your appointment today", "आज ही अपॉइंटमेंट बुक करें", tip="Show a clear booking number."),
    "coaching": _cat("Coaching / school", ["#EEF4FF", "#1D4ED8", "#0F172A"], "Admissions Open", "प्रवेश प्रारंभ", "Limited seats. Enrol today", "सीमित सीटें। आज ही नामांकन करें", "a4_portrait_300dpi", "Print A4 flyers and share the same design on WhatsApp."),
    "clinic": _cat("Clinic", ["#F0FDFA", "#0F766E", "#0B2B28"], "Your Health, Our Care", "आपकी सेहत, हमारी देखभाल", "Consult our doctors", "हमारे डॉक्टरों से मिलें", tip="Keep timings and address large."),
    "restaurant": _cat("Restaurant", ["#2B1810", "#F59E0B", "#FFF7E6"], "Taste That Feels Like Home", "घर जैसा स्वाद", "Dine in or order online", "यहीं खाएं या ऑनलाइन ऑर्डर करें", tip="Lead with a real food photo."),
    "real_estate": _cat("Real estate", ["#F8FAFC", "#0369A1", "#0F172A"], "Your Dream Home Awaits", "आपके सपनों का घर", "Book a site visit", "साइट विज़िट बुक करें", "facebook_post", "Add RERA number if you are required to show it."),
    "sale": _cat("Sale / offer", ["#FEF2F2", "#DC2626", "#1F1111"], "Mega Sale", "महा सेल", "Limited time offer", "सीमित समय का ऑफ़र", tip="One big number beats many small ones."),
}
PURPOSES = {
    "sale": ("instagram_post", ["Use one price or percentage as the biggest element.", "Add an end date."]),
    "festival": ("instagram_story", ["Greeting first, business name second.", "Use the festival's colour palette."]),
    "event": ("instagram_post", ["Show date, time and place together.", "Add a QR code for registration."]),
    "hiring": ("linkedin_post", ["State the role and location first.", "End with one way to apply."]),
    "launch": ("instagram_post", ["Show the product, not just text.", "Add a clear call to action."]),
}


def category_layers(c, w, h, business="", price=None, lang="en", digits="latin"):
    bg, accent, ink = c["palette"]
    m, num = round(w * .07), (lambda s: s.translate(DEV) if digits == "devanagari" else s)
    t = lambda name, text, y, hh, fs, col: S.new_layer(  # noqa: E731
        type="text", name=name, text=text, x=m, y=round(h * y), w=w - 2 * m, h=round(h * hh), font_size=round(w * fs), color=col)
    L = [S.new_layer(type="rect", name="Background", x=0, y=0, w=w, h=h, fill=bg),
         S.new_layer(type="rect", name="Accent bar", x=m, y=m, w=round(w * .18), h=max(4, round(h * .012)), fill=accent),
         t("Headline", c["headline"][lang], .12, .2, .1, ink), t("Subheading", c["sub"][lang], .36, .1, .045, ink)]
    if price is not None:
        L.append(t("Offer", num(inr(price)), .5, .15, .14, accent))
    if business:
        L.append(t("Business", business, .9, .05, .04, ink))
    return L

# ------------------------------------------------------------------ safety and storage
def safe_image(data: bytes, max_bytes=10_000_000, max_px=40_000_000) -> bytes:
    """Allow PNG/JPEG/WebP only, cap size/pixels, verify, and re-encode (drops metadata and appended payloads)."""
    if len(data) > max_bytes:
        raise ValueError("image is larger than 10 MB")
    im = Image.open(io.BytesIO(data))
    if im.format not in ("PNG", "JPEG", "WEBP"):
        raise ValueError("only PNG, JPEG and WebP images are accepted")
    if im.width * im.height > max_px:
        raise ValueError("image has too many pixels")
    im.verify()
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def check_font(data: bytes, max_bytes=10_000_000) -> None:
    if len(data) > max_bytes:
        raise ValueError("font is larger than 10 MB")
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise ValueError("not a valid TrueType/OpenType font")


def find_duplicates(root, referenced=()):
    ref, groups = {os.path.abspath(p) for p in referenced}, {}
    for d, _, files in os.walk(root):
        if os.path.basename(d) in ("fonts", "backups"):
            continue
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                path = os.path.abspath(os.path.join(d, f))
                with open(path, "rb") as fh:
                    groups.setdefault(hashlib.sha256(fh.read()).hexdigest(), []).append(path)
    out = []
    for paths in groups.values():
        if len(paths) > 1:
            paths.sort(key=lambda q: (q not in ref, os.path.getmtime(q)))  # keep a referenced file, else the oldest
            out.append({"keep": paths[0], "remove": [q for q in paths[1:] if q not in ref]})
    return out
