"""Code-only color intelligence (no AI model, no API, no cost).

Two layers:
  1. extract_brand_colors()  - K-Means dominant colors from one image
                               (kept for the /colors endpoint and old callers).
  2. build_design_palette()  - turns logo + poster colors into a *design
                               palette with roles* (primary, secondary, accent,
                               dark, light, gradient, readable text colors).
                               Footers and frames use these roles instead of
                               one flat logo color.
"""
from __future__ import annotations

import colorsys
import io
import math

import numpy as np
from PIL import Image

DEFAULT_PALETTE = ["#1F2937", "#F59E0B", "#FFFFFF"]
RGB = tuple[int, int, int]


# ----------------------------------------------------------- color helpers
def hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def rgb_to_hex(rgb: tuple[int, ...]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(c) for c in rgb[:3]))


# kept for backward compatibility with older code
_hex = rgb_to_hex


def luminance(rgb: RGB) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""
    def chan(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def saturation(rgb: RGB) -> float:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[1]


def distance(a: RGB, b: RGB) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Blend a->b. t=0 gives a, t=1 gives b."""
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore


def darken(rgb: RGB, amount: float) -> RGB:
    return mix(rgb, (0, 0, 0), amount)


def lighten(rgb: RGB, amount: float) -> RGB:
    return mix(rgb, (255, 255, 255), amount)


def readable_text_color(bg: RGB) -> RGB:
    """Near-white or near-black, whichever has better contrast on bg."""
    dark, light = (17, 17, 17), (255, 255, 255)
    return light if contrast_ratio(light, bg) >= contrast_ratio(dark, bg) else dark


def ensure_contrast(fg: RGB, bg: RGB, minimum: float = 4.5) -> RGB:
    """Nudge fg toward white/black until it is readable on bg."""
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    target = (255, 255, 255) if luminance(bg) < 0.5 else (0, 0, 0)
    for step in range(1, 21):
        candidate = mix(fg, target, step / 20)
        if contrast_ratio(candidate, bg) >= minimum:
            return candidate
    return readable_text_color(bg)


# ------------------------------------------------------ K-Means extraction
def _kmeans(pixels: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)  # deterministic
    k = max(1, min(k, len(pixels)))
    centroids = pixels[rng.choice(len(pixels), size=k, replace=False)]
    labels = np.zeros(len(pixels), dtype=int)
    for _ in range(15):
        d = ((pixels[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        labels = d.argmin(axis=1)
        new = np.array([pixels[labels == i].mean(axis=0)
                        if np.any(labels == i) else centroids[i]
                        for i in range(k)])
        if np.allclose(new, centroids):
            break
        centroids = new
    return centroids, labels


def extract_brand_colors(image_bytes: bytes, k: int = 5,
                         skip_background: bool = False) -> dict:
    """K-Means dominant colors, most common first.

    Transparent pixels are always ignored. With skip_background=True, near-white
    pixels are ignored too (use for logos on white backgrounds).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        img.thumbnail((128, 128), Image.LANCZOS)
        arr = np.asarray(img).reshape(-1, 4)
        keep = arr[:, 3] > 20
        rgb = arr[:, :3].astype(float)
        if skip_background:
            keep &= ~(rgb.min(axis=1) > 235)
        pixels = rgb[keep]
        if len(pixels) < 8:  # nothing left (e.g. all-white logo): use everything
            pixels = arr[:, :3].astype(float)
        centroids, labels = _kmeans(pixels, k)
        counts = np.bincount(labels, minlength=len(centroids))
        order = counts.argsort()[::-1]
        return {
            "colors": [rgb_to_hex(tuple(int(c) for c in centroids[i])) for i in order],
            "method": "kmeans_numpy",
            "proportions": [round(float(counts[i]) / len(pixels), 4) for i in order],
        }
    except Exception as exc:  # noqa: BLE001
        return {"colors": DEFAULT_PALETTE, "method": "default_palette",
                "error": str(exc)}


# ------------------------------------------------------- design palette
def _vivid(rgb: RGB) -> bool:
    return saturation(rgb) > 0.28 and 0.015 < luminance(rgb) < 0.85


def _gold_for(primary: RGB) -> RGB:
    """Warm accent that works on most brand colors."""
    gold = (230, 176, 60)
    return gold if distance(gold, primary) > 110 else (250, 235, 200)


def build_design_palette(logo_bytes: bytes | None = None,
                         poster_bytes: bytes | None = None) -> dict:
    """Build a palette with design roles from the logo and/or the poster.

    Logo colors define the brand (primary/secondary). Poster colors help pick
    an accent that sits well with the artwork, so the footer feels part of
    the poster instead of pasted on.
    """
    logo_cols: list[RGB] = []
    poster_cols: list[RGB] = []
    if logo_bytes:
        res = extract_brand_colors(logo_bytes, k=6, skip_background=True)
        logo_cols = [hex_to_rgb(c) for c in res["colors"]]
    if poster_bytes:
        res = extract_brand_colors(poster_bytes, k=6)
        poster_cols = [hex_to_rgb(c) for c in res["colors"]]

    brand = logo_cols or poster_cols or [hex_to_rgb(c) for c in DEFAULT_PALETTE]
    vivid = [c for c in brand if _vivid(c)]
    primary = vivid[0] if vivid else brand[0]

    # secondary: another brand color that is clearly different from primary
    pool = vivid[1:] + [c for c in brand if c not in vivid]
    secondary = next((c for c in pool if distance(c, primary) > 90), None)
    if secondary is None:
        secondary = lighten(primary, 0.35) if luminance(primary) < 0.5 \
            else darken(primary, 0.35)

    # accent: vivid poster color that contrasts with primary, else brand gold
    # a poster color only becomes the accent if it is bright and saturated
    # (so it POPS on the artwork); otherwise use a warm gold/cream accent.
    accent = next((c for c in poster_cols
                   if saturation(c) > 0.35 and luminance(c) > 0.30
                   and distance(c, primary) > 110
                   and distance(c, secondary) > 60), None) or _gold_for(primary)

    dark = darken(primary, 0.55)
    light = lighten(primary, 0.88)
    deep = darken(primary, 0.30)
    return {
        "primary": rgb_to_hex(primary),
        "secondary": rgb_to_hex(secondary),
        "accent": rgb_to_hex(accent),
        "dark": rgb_to_hex(dark),
        "light": rgb_to_hex(light),
        "gradient": [rgb_to_hex(deep), rgb_to_hex(lighten(primary, 0.10))],
        "text_on_primary": rgb_to_hex(readable_text_color(primary)),
        "text_on_dark": rgb_to_hex(readable_text_color(dark)),
        "accent_text": rgb_to_hex(ensure_contrast(accent, deep, 3.0)),
        "source": ("logo+poster" if logo_cols and poster_cols else
                   "logo" if logo_cols else
                   "poster" if poster_cols else "default"),
        "all_colors": [rgb_to_hex(c) for c in brand],
    }
