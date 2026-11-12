"""Compose engine: prompt -> poster -> headline -> footer -> frame -> final.

Division of labour (this is what makes results reliable AND good looking):
  * The AI model paints the poster ARTWORK (it is good at that).
  * Code draws everything that must be exact: headline text (English or
    Hindi), footer shapes, contact details, logo, CTA button, frame.
    Phone numbers and spelling are therefore never garbled by an AI model.

What is new vs the first version:
  * Palette ROLES (primary/secondary/accent/dark/gradient) built from the logo
    AND the poster (see colors.build_design_palette), not one flat color.
  * 8 footer designs (rectangle, rounded, wave, diagonal, curved, double,
    floating, layered) with gradients, accent edge lines, soft shadows and a
    subtle dot pattern. When no style is chosen, one is picked per design
    instead of always using the same rectangle.
  * Logo is shown without a white box (transparent logos used as-is; plain
    backgrounds removed; a soft round badge only if contrast is poor).
  * CTA rendered as a pill button; contact lines laid out beside the logo.
  * Typography engine: headline + subheading with auto-fit, shadow, scrim for
    readability, Devanagari support (fonts in assets/fonts).
  * 2x supersampling for smooth edges; optional 2K/4K generation.
  * Missing details are omitted, never filled with dummy data.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import time
from functools import lru_cache
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .colors import (build_design_palette, contrast_ratio, darken, distance,
                     ensure_contrast, extract_brand_colors, hex_to_rgb,
                     lighten, luminance, mix, readable_text_color, saturation,
                     DEFAULT_PALETTE)
from .prompt_builder import build_prompt

SS = 2  # supersampling factor for footer drawing
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR = os.path.join(ROOT, "assets", "fonts")

FRAME_SHAPE_MAP = {
    "rectangle": "rectangle", "rounded": "rounded", "capsule": "rounded",
    "arch": "rounded", "floating": "floating", "double": "double",
    "double_layer": "double", "ribbon": "double", "wave": "rounded",
    "diagonal": "rectangle", "split": "double", "transparent": "rectangle",
}
FOOTER_STYLES = ("rectangle", "rounded", "wave", "diagonal", "curved",
                 "double", "floating", "layered")
FOOTER_SHAPE_MAP = {
    "rectangle": "rectangle", "full_width": "rectangle", "rounded": "rounded",
    "capsule": "rounded", "arch": "curved", "curved": "curved",
    "floating": "floating", "wave": "wave", "diagonal": "diagonal",
    "ribbon": "diagonal", "double": "double", "layered": "layered",
    "split": "layered", "transparent": "rounded",
}
# used when nothing is chosen, so footers do not all look the same
AUTO_STYLES = ("curved", "wave", "diagonal", "double", "layered", "floating")


# ------------------------------------------------------------------ helpers
def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(lo, min(hi, number))


def pick_palette(colors: list[str]) -> tuple[tuple, tuple]:
    """Back-compat helper: (primary, secondary) from a list of hex colors."""
    rgbs = [hex_to_rgb(c) for c in (colors or DEFAULT_PALETTE)]
    vivid = [c for c in rgbs if saturation(c) > 0.25 and 0.015 < luminance(c) < 0.85]
    primary = vivid[0] if vivid else rgbs[0]
    secondary = next((c for c in rgbs if distance(c, primary) > 80), None)
    if secondary is None:
        secondary = (255, 255, 255) if luminance(primary) < 0.5 else (30, 30, 30)
    return primary, secondary


def _script(text: str) -> str:
    return "devanagari" if any("\u0900" <= ch <= "\u097f" for ch in text) else "latin"


def _font_path(name: str) -> str:
    return os.path.join(FONT_DIR, name)


def has_devanagari_font() -> bool:
    return os.path.exists(_font_path("NotoSansDevanagari-Variable.ttf"))


@lru_cache(maxsize=256)
def _font(size: int, bold: bool = False, script: str = "latin"):
    size = max(8, int(size))
    if script == "devanagari":
        try:
            f = ImageFont.truetype(_font_path("NotoSansDevanagari-Variable.ttf"), size)
            try:
                f.set_variation_by_axes([700 if bold else 400, 100])  # weight, width
            except Exception:  # noqa: BLE001 - static font
                pass
            return f
        except OSError:
            pass
    names = (["Poppins-Bold.ttf"] if bold else ["Poppins-Regular.ttf"])
    candidates = [_font_path(n) for n in names] + (
        ["DejaVuSans-Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"] if bold
        else ["DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf"])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _vgradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    t = np.linspace(0, 1, h)[:, None, None]
    arr = np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t
    return Image.fromarray(np.repeat(arr, w, axis=1).astype(np.uint8), "RGB")


def _over(base: Image.Image, fill, mask: Image.Image) -> Image.Image:
    """Alpha-composite `fill` (RGB image or color) through `mask` onto base."""
    if not isinstance(fill, Image.Image):
        fill = Image.new("RGB", base.size, tuple(fill[:3]))
    layer = fill.convert("RGBA")
    layer.putalpha(mask)
    return Image.alpha_composite(base, layer)


def _edge_mask(W: int, H: int, edge: Callable[[float], float]) -> tuple[Image.Image, list]:
    pts = [(x, edge(x)) for x in range(0, W + 1, 2)]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(pts + [(W, H), (0, H)], fill=255)
    return mask, pts


def _shadow(base: Image.Image, mask: Image.Image, blur: int, dy: int,
            alpha: int = 90) -> Image.Image:
    m = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: v * alpha // 255)
    m = ImageChops.offset(m, 0, dy)
    return _over(base, (0, 0, 0), m)


def _dots(base: Image.Image, mask: Image.Image, color: tuple) -> Image.Image:
    """Very subtle dot pattern inside a shape (decorative texture)."""
    W, H = base.size
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    step, r = 26 * SS, 2 * SS
    for y in range(step // 2, H, step):
        for x in range(step // 2 + ((y // step) % 2) * step // 2, W, step):
            d.ellipse([x - r, y - r, x + r, y + r], fill=26)
    return _over(base, color, ImageChops.multiply(layer, mask))


# --------------------------------------------------------------------- logo
def prepare_logo(logo: Image.Image) -> Image.Image:
    """Return an RGBA logo with a transparent background, cropped to content.

    Transparent logos are used as they are. For logos on a plain background the
    background is removed by flood-filling from the corners (only if the
    corners agree). If removal would delete almost everything, the original is
    kept. This is what avoids the ugly white box behind logos.
    """
    logo = logo.convert("RGBA")
    alpha = np.asarray(logo)[:, :, 3]
    if (alpha < 250).mean() > 0.02:  # already has real transparency
        pass
    else:
        corners = [logo.getpixel(p) for p in
                   ((0, 0), (logo.width - 1, 0), (0, logo.height - 1),
                    (logo.width - 1, logo.height - 1))]
        if max(distance(c[:3], corners[0][:3]) for c in corners) < 40:
            work = logo.copy()
            for p in ((0, 0), (work.width - 1, 0), (0, work.height - 1),
                      (work.width - 1, work.height - 1)):
                try:
                    ImageDraw.floodfill(work, p, (0, 0, 0, 0), thresh=60)
                except Exception:  # noqa: BLE001
                    pass
            if (np.asarray(work)[:, :, 3] > 10).mean() > 0.08:
                logo = work
    bbox = logo.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    return logo.crop(bbox) if bbox else logo


def _logo_mean_color(logo: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(logo.convert("RGBA")).reshape(-1, 4)
    arr = arr[arr[:, 3] > 40]
    return tuple(int(v) for v in arr[:, :3].mean(0)) if len(arr) else (255, 255, 255)


# -------------------------------------------------------------------- frame
def render_frame(width: int, height: int, shape: str, primary, secondary,
                 thickness: int, padding: int) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [padding, padding, width - padding - 1, height - padding - 1]
    radius = 0 if shape == "rectangle" else thickness * 3
    d.rounded_rectangle(box, radius=radius, outline=tuple(primary) + (255,),
                        width=thickness)
    if shape in ("double", "rectangle"):
        gap = int(thickness * 1.6)
        inner = [box[0] + gap, box[1] + gap, box[2] - gap, box[3] - gap]
        d.rounded_rectangle(inner, radius=max(0, radius - gap // 2),
                            outline=tuple(secondary) + (255,),
                            width=max(2, thickness // 3))
    return img


# ------------------------------------------------------------------- footer
def footer_lines(business: str, d: dict, include_cta: bool = True) -> list[tuple[str, bool]]:
    """Only fields the user filled in are shown (no empty contact rows)."""
    g = lambda k: str(d.get(k) or "").strip()  # noqa: E731
    lines: list[tuple[str, bool]] = []
    if business.strip():
        lines.append((business.strip(), True))
    if include_cta and g("cta"):
        lines.append((g("cta"), False))
    contact = []
    if g("phone"):
        contact.append(f"Call: {g('phone')}")
    if g("whatsapp"):
        contact.append(f"WhatsApp: {g('whatsapp')}")
    web = [x for x in (g("website"), g("email")) if x]
    for group in (contact, web):
        for i in range(0, len(group), 2):
            lines.append(("   |   ".join(group[i:i + 2]), False))
    if g("address"):
        lines.append((g("address"), False))
    return lines


def _draw_text_block(d: ImageDraw.ImageDraw, box, lines, color, align: str,
                     title_color=None) -> bool:
    """Auto-fit lines into box. Returns False if even the smallest size overflows."""
    if not lines:
        return True
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    size = max(10, int(bh / (len(lines) * 1.3 + 0.35)))
    fits, fonts, heights = False, [], []
    while size >= 10:
        fonts = [_font(int(size * (1.5 if t else 1.0)), t, _script(txt))
                 for txt, t in lines]
        heights = [int(f.size * 1.22) for f in fonts]
        widest = max(d.textlength(txt, font=f) for (txt, _), f in zip(lines, fonts))
        if widest <= bw and sum(heights) <= bh:
            fits = True
            break
        size -= 1
    y = y0 + (bh - sum(heights)) / 2
    for (txt, is_title), f, h in zip(lines, fonts, heights):
        col = (title_color if (is_title and title_color) else color) + (255,)
        if align == "left":
            d.text((x0, y + h / 2), txt, font=f, fill=col, anchor="lm")
        else:
            d.text((x0 + bw / 2, y + h / 2), txt, font=f, fill=col, anchor="mm")
        y += h
    return fits


def render_footer(width: int, height: int, shape: str, position: str,
                  primary, secondary, lines: list[tuple[str, bool]],
                  logo: Image.Image | None = None, *, accent=None, cta: str = "",
                  text_color=None) -> tuple[Image.Image, bool]:
    """Draw one footer design. Returns (RGBA image, text_fits).

    shape: rectangle | rounded | wave | diagonal | curved | double |
           floating | layered   (unknown names fall back to rectangle)
    """
    W, H = width * SS, height * SS
    primary, secondary = tuple(primary), tuple(secondary)
    accent = tuple(accent) if accent else (
        (230, 176, 60) if distance((230, 176, 60), primary) > 110 else (250, 235, 200))
    deep = darken(primary, 0.32)
    fill = _vgradient(W, H, lighten(primary, 0.10), deep)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pad_x, pad_b = int(W * 0.04), int(H * 0.10)

    def sine(c, amp, cycles, phase=0.0):
        return lambda x: c + amp * math.sin(x / W * cycles * 2 * math.pi + phase)

    box_top = int(H * 0.12)
    front_mask = None

    if shape in ("wave", "curved", "diagonal", "layered"):
        if shape == "wave":
            back_edge = sine(H * 0.16, H * 0.10, 2)
            front_edge = sine(H * 0.26, H * 0.08, 2, 0.8)
            box_top = int(H * 0.42)
        elif shape == "curved":
            front_edge = lambda x: 0.30 * H * ((2 * x / W - 1) ** 2)  # noqa: E731
            back_edge = lambda x: front_edge(x) - 0.06 * H  # noqa: E731
            box_top = int(H * 0.36)
        elif shape == "diagonal":
            front_edge = lambda x: 0.34 * H - 0.30 * H * x / W  # noqa: E731
            back_edge = lambda x: front_edge(x) - 0.08 * H  # noqa: E731
            box_top = int(H * 0.40)
        else:  # layered: three stacked waves
            l1 = sine(H * 0.10, H * 0.06, 1.5)
            l2 = sine(H * 0.20, H * 0.06, 1.5, 1.0)
            front_edge = sine(H * 0.30, H * 0.05, 1.5, 2.0)
            m1, _ = _edge_mask(W, H, l1)
            img = _over(img, accent, m1)
            back_edge = l2
            box_top = int(H * 0.44)
        back_mask, _ = _edge_mask(W, H, back_edge)
        img = _over(img, secondary, back_mask)
        front_mask, pts = _edge_mask(W, H, front_edge)
        img = _over(img, fill, front_mask)
        ImageDraw.Draw(img).line(pts, fill=accent + (255,), width=3 * SS)
    elif shape in ("rounded", "floating"):
        m = int(W * (0.02 if shape == "rounded" else 0.04))
        vy = int(H * (0.08 if shape == "rounded" else 0.12))
        card = [m, vy, W - m, H - vy]
        radius = int((card[3] - card[1]) * (0.30 if shape == "rounded" else 0.5))
        front_mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(front_mask).rounded_rectangle(card, radius=radius, fill=255)
        img = _shadow(img, front_mask, 8 * SS, 4 * SS)
        img = _over(img, fill, front_mask)
        ImageDraw.Draw(img).rounded_rectangle(
            card, radius=radius, outline=accent + (255,),
            width=(2 if shape == "rounded" else 3) * SS)
        pad_x, box_top, pad_b = m + int(W * 0.04), vy + int(H * 0.08), vy + int(H * 0.06)
    else:  # rectangle, double
        front_mask = Image.new("L", (W, H), 255)
        img = _over(img, fill, front_mask)
        d0 = ImageDraw.Draw(img)
        if shape == "double":
            inset = int(H * 0.10)
            d0.rounded_rectangle([inset, inset, W - inset, H - inset],
                                 radius=int(H * 0.18), outline=accent + (255,),
                                 width=3 * SS)
            pad_x, box_top, pad_b = inset + int(W * 0.03), inset + int(H * 0.06), inset + int(H * 0.05)
        else:
            d0.rectangle([0, 0, W, max(3, int(H * 0.05))], fill=accent + (255,))
            box_top = int(H * 0.14)

    img = _dots(img, front_mask, lighten(primary, 0.6))

    box = [pad_x, box_top, W - pad_x, H - pad_b]
    if position == "top":  # mirror the artwork, keep the text upright
        img = ImageOps.flip(img)
        box = [box[0], H - box[3], box[2], H - box[1]]

    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    bh, bw = y1 - y0, x1 - x0
    text_col = tuple(text_color) if text_color else readable_text_color(deep)
    title_col = text_col

    # --- logo (no white box; a soft round badge only when contrast is poor) ---
    left = x0
    if logo is not None and bh > 10:
        lg = logo.copy()
        side = int(min(bh, bw * 0.30))
        lg.thumbnail((side, side), Image.LANCZOS)
        ly = y0 + (bh - lg.height) // 2
        if contrast_ratio(_logo_mean_color(lg), deep) < 2.2:
            r = int(max(lg.width, lg.height) * 0.62)
            cx, cy = x0 + lg.width // 2, ly + lg.height // 2
            badge = Image.new("L", (W, H), 0)
            ImageDraw.Draw(badge).ellipse([cx - r, cy - r, cx + r, cy + r], fill=235)
            img = _over(img, lighten(primary, 0.92), badge)
            d = ImageDraw.Draw(img)
        img.alpha_composite(lg, (x0, ly))
        left = x0 + lg.width + int(W * 0.03)

    # --- CTA pill on the right ---
    right = x1
    cta = (cta or "").strip()
    if cta and bh > 10:
        fs = int(bh * 0.30)
        font = _font(fs, True, _script(cta))
        pill_w = d.textlength(cta, font=font) + 2 * int(bh * 0.24)
        while pill_w > 0.34 * bw and fs > 12:
            fs -= 1
            font = _font(fs, True, _script(cta))
            pill_w = d.textlength(cta, font=font) + 2 * int(bh * 0.24)
        if pill_w <= 0.34 * bw:
            ph = int(bh * 0.55)
            py = y0 + (bh - ph) // 2
            px = x1 - int(pill_w)
            d.rounded_rectangle([px, py, x1, py + ph], radius=ph // 2,
                                fill=accent + (255,))
            d.text((px + pill_w / 2, py + ph / 2), cta, font=font,
                   fill=readable_text_color(accent) + (255,), anchor="mm")
            right = px - int(W * 0.02)
        else:  # too long for a button: show it as a normal line instead
            lines = lines[:1] + [(cta, False)] + lines[1:]

    align = "left" if (logo is not None or right != x1) else "center"
    fits = _draw_text_block(d, (left, y0, right, y1), lines, text_col, align, title_col)
    return img.resize((width, height), Image.LANCZOS), fits


# --------------------------------------------------------------- typography
def draw_headline(poster: Image.Image, headline: str, subheading: str,
                  pal: dict, warnings: list[str], top_clear: int = 0) -> Image.Image:
    """Draw headline + subheading in the upper part of the poster.

    Auto-fits and wraps text, adds a soft shadow, and a gentle dark/light scrim
    when the artwork behind the text would make it hard to read.
    """
    headline, subheading = (headline or "").strip(), (subheading or "").strip()
    if not headline and not subheading:
        return poster
    if any(_script(t) == "devanagari" for t in (headline, subheading)) \
            and not has_devanagari_font():
        warnings.append("Hindi text needs assets/fonts/NotoSansDevanagari-Variable.ttf "
                        "(not found) - text may not display correctly.")
    poster = poster.convert("RGBA")
    W, H = poster.size
    zy0 = max(int(H * 0.05), int(top_clear))  # top_clear: keep clear of a top footer
    zx0, zx1, zy1 = int(W * 0.08), int(W * 0.92), zy0 + int(H * 0.25)
    region = np.asarray(poster.crop((zx0, zy0, zx1, zy1)).convert("RGB")).reshape(-1, 3)
    mean = tuple(int(v) for v in region.mean(0))
    accent = hex_to_rgb(pal["accent"])
    head_col = ensure_contrast(accent, mean, 3.5)
    if contrast_ratio(head_col, mean) < 3:
        head_col = readable_text_color(mean)
    sub_col = readable_text_color(mean)

    # scrim: only when readability is doubtful
    if contrast_ratio(head_col, mean) < 6:
        scrim_col = (0, 0, 0) if luminance(head_col) > luminance(mean) else (255, 255, 255)
        fade = np.linspace(0.42, 0.0, int(H * 0.40))[:, None]
        alpha = np.zeros((H, W))
        alpha[:fade.shape[0], :] = fade
        poster = _over(poster, scrim_col, Image.fromarray((alpha * 255).astype(np.uint8), "L"))

    d = ImageDraw.Draw(poster)
    zone_w, zone_h = zx1 - zx0, zy1 - zy0

    def wrap(text, font, max_lines):
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if d.textlength(trial, font=font) <= zone_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines if len(lines) <= max_lines else None

    size = int(H * 0.085)
    h_lines, s_lines, hf, sf = [], [], None, None
    while size >= 14:
        hf = _font(size, True, _script(headline or subheading))
        sf = _font(int(size * 0.42), False, _script(subheading or headline))
        h_lines = wrap(headline, hf, 3) if headline else []
        s_lines = wrap(subheading, sf, 2) if subheading else []
        if h_lines is not None and s_lines is not None:
            total = len(h_lines) * size * 1.25 + len(s_lines) * size * 0.42 * 1.35
            if total <= zone_h:
                break
        size -= 2
    h_lines, s_lines = h_lines or [], s_lines or []

    items = [(t, hf, head_col, size * 1.25) for t in h_lines] + \
            [(t, sf, sub_col, size * 0.42 * 1.35) for t in s_lines]
    y = zy0 + (zone_h - sum(i[3] for i in items)) / 2
    shadow = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shadow)
    for text, font, _, lh in items:
        sd.text((W / 2, y + lh / 2 + size * 0.04), text, font=font, fill=170, anchor="mm")
        y += lh
    poster = _over(poster, (0, 0, 0), shadow.filter(ImageFilter.GaussianBlur(max(2, size * 0.05))))
    d = ImageDraw.Draw(poster)
    y = zy0 + (zone_h - sum(i[3] for i in items)) / 2
    for text, font, col, lh in items:
        d.text((W / 2, y + lh / 2), text, font=font, fill=col + (255,), anchor="mm")
        y += lh
    return poster


# ---------------------------------------------------------------- pipeline
def _suggest(registry, kind: str, business: str, details: dict) -> dict | None:
    try:
        res = registry.run("suggest_layout", {"kind": kind, "business": business,
                                               "details": details})
        # the mock provider's layout is a fixed placeholder, not a real design idea
        if res.success and isinstance(res.data, dict) and res.provider != "mock":
            return res.data
    except Exception:  # noqa: BLE001 - provider lacks the feature, etc.
        pass
    return None


def compose_poster(registry, prompt: str, business: str = "",
                   details: dict | None = None, logo_bytes: bytes | None = None,
                   style: str = "", width: int = 1024, height: int = 1024,
                   footer_position: str = "bottom", *, headline: str = "",
                   subheading: str = "", footer_style: str = "auto",
                   mode: str = "artwork", image_size: str = "1K",
                   poster_bytes: bytes | None = None) -> dict:
    """Build the complete poster.

    mode="artwork": model paints art only; headline/footer drawn by code (default).
    mode="poster" : model also renders the headline text itself.
    poster_bytes  : use your own poster instead of generating one (free testing).
    """
    details = details or {}
    warnings: list[str] = []

    # logo + early palette (also steers the artwork colors)
    logo_img = None
    if logo_bytes:
        try:
            logo_img = prepare_logo(Image.open(io.BytesIO(logo_bytes)))
        except Exception:  # noqa: BLE001
            logo_bytes = None
            warnings.append("Logo could not be read; used poster colors instead.")
    logo_pal = build_design_palette(logo_bytes) if logo_bytes else None

    # 1) poster artwork
    final_prompt, provider_name, model_id = "(uploaded poster)", "uploaded", "-"
    if poster_bytes:
        raw = poster_bytes
    else:
        try:
            final_prompt = build_prompt(
                prompt, style, width, height, mode=mode, headline=headline,
                subheading=subheading,
                palette=[logo_pal["primary"], logo_pal["accent"]] if logo_pal else None,
                reserve_headline=bool(headline or subheading) and mode == "artwork")
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        try:
            gen = registry.run("generate_image", {
                "prompt": final_prompt, "width": width, "height": height,
                "image_size": image_size})
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
        if not gen.success:
            return {"success": False, "error": gen.error}
        raw, provider_name, model_id = gen.data, gen.provider, gen.model_id
        if provider_name == "mock":
            warnings.append("Poster background is a MOCK placeholder, not AI output. "
                            "Switch the provider to a real model for a real poster.")
    # fill-crop (never stretch) to the exact requested size
    poster = ImageOps.fit(Image.open(io.BytesIO(raw)).convert("RGB"),
                          (width, height), Image.LANCZOS)

    # 2) palette with roles (logo + poster together)
    pal = build_design_palette(logo_bytes, raw)
    primary, secondary, accent = (hex_to_rgb(pal[k]) for k in ("primary", "secondary", "accent"))
    arr = np.asarray(poster)
    t = max(2, int(min(width, height) * 0.03))  # outer 3% strip = what the frame sits on
    edge = np.concatenate([arr[:t].reshape(-1, 3), arr[-t:].reshape(-1, 3),
                           arr[:, :t].reshape(-1, 3), arr[:, -t:].reshape(-1, 3)])
    frame_col = ensure_contrast(accent, tuple(int(v) for v in edge.mean(0)), 2.5)

    # 3) layout suggestions (contact details are NOT sent to the model)
    hint = {"style": style, "poster_prompt": prompt, "palette": pal["all_colors"][:3]}
    fl = _suggest(registry, "frame", business, hint)
    ft = _suggest(registry, "footer", business, hint)
    if fl is None or ft is None:
        warnings.append("AI layout suggestion unavailable; used rule-based defaults.")
    fl, ft = fl or {}, ft or {}

    base = min(width, height)
    f_shape = FRAME_SHAPE_MAP.get(str(fl.get("shape", "")).lower(), "double")
    thickness = int(_num(fl.get("border_thickness"), base * 0.016,
                         base * 0.008, base * 0.04))
    padding = int(_num(fl.get("padding"), 0 if f_shape in ("rectangle", "double")
                       else thickness * 0.6, 0, thickness * 3))
    if f_shape == "floating":
        f_shape, padding = "rounded", max(padding, thickness * 2)
    inset = padding + thickness

    # footer design: explicit choice > model suggestion > varied automatic pick
    if footer_style in FOOTER_STYLES:
        shape = footer_style
    elif ft.get("shape") and str(ft["shape"]).lower() in FOOTER_SHAPE_MAP:
        shape = FOOTER_SHAPE_MAP[str(ft["shape"]).lower()]
    else:
        digest = hashlib.md5(f"{prompt}|{business}".encode()).digest()[0]
        shape = AUTO_STYLES[digest % len(AUTO_STYLES)]
    pos = "top" if footer_position == "top" else "bottom"

    cta = str(details.get("cta") or "").strip()
    lines = footer_lines(business, details, include_cta=False)
    n_rows = len(lines) + (1 if cta else 0)
    if ft.get("height_ratio") is not None:
        ratio = _num(ft.get("height_ratio"), 0.15, 0.10, 0.22)
    elif ft.get("height_px") is not None:
        ratio = _num(ft.get("height_px"), height * 0.15, height * 0.10, height * 0.22) / height
    else:
        ratio = _num(0.09 + 0.026 * n_rows, 0.15, 0.12, 0.24)
    fh = int(height * ratio)

    # 4) headline (artwork mode; moves below a top footer), footer, frame
    canvas = poster.convert("RGBA")
    headline_drawn = False
    if mode == "artwork" and (headline.strip() or subheading.strip()):
        clear = (inset + fh + int(height * 0.02)) if pos == "top" else 0
        canvas = draw_headline(canvas, headline, subheading, pal, warnings, clear)
        headline_drawn = True
    footer_img, fits = render_footer(
        width - 2 * inset, fh, shape, pos, primary, secondary, lines, logo_img,
        accent=accent, cta=cta)
    if not fits:
        warnings.append("Footer text is very long; it was shrunk to the minimum size.")

    # frame: gold-style accent outside, brand color inside
    frame_img = render_frame(width, height, f_shape, frame_col, primary, thickness, padding)
    fy = inset if pos == "top" else height - fh - inset
    canvas.alpha_composite(footer_img, (inset, fy))
    canvas.alpha_composite(frame_img)
    final = canvas.convert("RGB")

    # 5) save everything (originals are never overwritten)
    out_dir = os.path.join(registry.output_dir, "compose", str(int(time.time() * 1000)))
    os.makedirs(out_dir, exist_ok=True)
    paths = {"poster": "poster.png", "frame": "frame.png",
             "footer": "footer.png", "final": "final.png"}
    poster.save(os.path.join(out_dir, paths["poster"]))
    frame_img.save(os.path.join(out_dir, paths["frame"]))
    footer_img.save(os.path.join(out_dir, paths["footer"]))
    final.save(os.path.join(out_dir, paths["final"]))
    buf = io.BytesIO()
    final.save(buf, format="PNG")

    meta = {
        "original_prompt": prompt, "final_prompt": final_prompt, "mode": mode,
        "provider": provider_name, "model_id": model_id, "image_size": image_size,
        "size": [width, height], "palette": pal, "headline_drawn": headline_drawn,
        "frame": {"shape": f_shape, "thickness": thickness, "padding": padding},
        "footer": {"shape": shape, "height": fh, "position": pos,
                   "cta_button": cta or None,
                   "lines": [t for t, _ in lines]},
        "warnings": warnings,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh_:
        json.dump(meta, fh_, indent=2, ensure_ascii=False)
    return {"success": True,
            "files": {k: os.path.join(out_dir, v) for k, v in paths.items()},
            "meta": meta, "final_bytes": buf.getvalue()}
