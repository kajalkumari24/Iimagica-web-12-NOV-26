"""Shared helpers for HTTP image providers."""
from __future__ import annotations

import io

from PIL import Image


def to_png(data: bytes) -> bytes:
    """Verify the payload is an image and normalise it to PNG (providers return JPEG/WebP/PNG)."""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        raise RuntimeError("Provider did not return an image: " + data[:200].decode("utf-8", "replace")) from None
    out = io.BytesIO()
    im.convert("RGB").save(out, "PNG")
    return out.getvalue()


def http_error(resp) -> RuntimeError:
    """Keeps the status code in the text so quota/rate-limit errors (429...) can be detected."""
    return RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
