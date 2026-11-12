"""Code-only image utilities (no model needed): background removal, upscale."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter


def remove_background(data: bytes, tolerance: int = 40) -> bytes:
    """Make the background transparent.

    Background colour = median of the border pixels; pixels within `tolerance`
    of it AND connected to the border are removed (flood fill), so matching
    colours inside the subject survive. Returns PNG bytes.
    """
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])[:, :3]
    bg = np.median(border, axis=0)
    near = np.abs(arr[:, :, :3] - bg).max(axis=2) <= tolerance

    reach = np.zeros((h, w), bool)
    stack = [(y, x) for y in (0, h - 1) for x in range(w)] + \
            [(y, x) for x in (0, w - 1) for y in range(h)]
    while stack:
        y, x = stack.pop()
        if 0 <= y < h and 0 <= x < w and near[y, x] and not reach[y, x]:
            reach[y, x] = True
            stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]

    alpha = Image.fromarray(np.where(reach, 0, 255).astype(np.uint8))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))  # soften edge
    img.putalpha(alpha)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def upscale(data: bytes, scale: int = 2, max_side: int = 4096) -> bytes:
    """Lanczos upscale by 2-4x (capped at max_side). Returns PNG bytes."""
    if not 1 <= scale <= 4:
        raise ValueError("scale must be between 1 and 4")
    img = Image.open(io.BytesIO(data))
    w, h = img.size
    f = min(scale, max_side / max(w, h))
    img = img.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
