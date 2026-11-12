"""Reject an identical AI request while the same one is still running (double-clicks, retries)."""
import hashlib
import time

from fastapi import Request
from fastapi.responses import JSONResponse

GUARDED = {"/generate", "/edit", "/variations", "/bulk", "/compare", "/benchmark", "/generate/fallback",
           "/region-edit", "/style-transfer", "/replace-background", "/remove-object", "/expand", "/replace-subject-bg",
           "/model-lab/benchmark", "/model-lab/test-connection"}
TTL = 180  # seconds; stale claims expire
_inflight: dict[str, float] = {}


def key(path: str, body: bytes) -> str:
    return hashlib.sha256(path.encode() + b"\0" + body).hexdigest()


def claim(k: str, now: float | None = None) -> bool:
    now = now or time.time()
    t = _inflight.get(k)
    if t and now - t < TTL:
        return False
    _inflight[k] = now
    return True


async def dedupe_middleware(request: Request, call_next):
    if request.method != "POST" or request.url.path not in GUARDED:
        return await call_next(request)
    body = await request.body()
    k = key(request.url.path, body)
    if not claim(k):
        return JSONResponse({"detail": "An identical request is already running. Wait for it to finish."}, status_code=409)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    try:
        return await call_next(Request(request.scope, receive))
    finally:
        _inflight.pop(k, None)
