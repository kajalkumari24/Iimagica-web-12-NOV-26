"""Design checks, Indian formats, safety, storage, guard and the new routes (mock provider)."""
from __future__ import annotations

import base64
import io
import os
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import guard
from app.core import quality as Q
from app.core import studio as S
from app.core.store import JsonStore


def png(color=(10, 10, 10), size=(50, 50)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
T = lambda **k: S.new_layer(type="text", **k)  # noqa: E731


def messy():
    return S.new_project("t", 1000, 1000, [
        T(text="Sale", x=20, y=400, w=300, h=100, font_size=60, color="#FFFFFF"),
        T(text="Overlap", x=40, y=420, w=300, h=100, font_size=60, color="#000000"),
        S.new_layer(type="image", x=100, y=700, w=400, h=400, src_base64=b64(png()))])


def test_inr_and_dates():
    assert Q.inr(1234567) == "₹12,34,567" and Q.inr(999) == "₹999" and Q.inr(100000) == "₹1,00,000"
    assert Q.inr(1499.5) == "₹1,499.50"
    import datetime as dt
    assert Q.indian_date(dt.date(2026, 11, 11), "hi") == "11 नवंबर 2026"


def test_checks_and_autofix():
    p = messy()
    kinds = {i["kind"] for i in Q.check_design(p)["issues"]}
    assert {"contrast", "safe_margin", "overlap", "low_resolution"} <= kinds
    layers, applied = Q.auto_fix(p)
    assert applied
    S.commit(p, layers)
    after = {i["kind"] for i in Q.check_design(p)["issues"]}
    assert not ({"contrast", "safe_margin"} & after)


def test_upload_safety(tmp_path):
    assert Q.safe_image(png())[:4] == b"\x89PNG"
    gif = io.BytesIO()
    Image.new("RGB", (5, 5)).save(gif, "GIF")
    for bad in (gif.getvalue(), b"not an image"):
        with pytest.raises(Exception):
            Q.safe_image(bad)
    with pytest.raises(ValueError):
        Q.safe_image(png(size=(100, 100)), max_px=50)
    with pytest.raises(ValueError):
        Q.check_font(b"junk")
    Q.check_font(b"OTTO" + b"\0" * 10)
    for n in "ab":
        (tmp_path / f"{n}.png").write_bytes(png())
    (tmp_path / "c.png").write_bytes(png((1, 2, 3)))
    d = Q.find_duplicates(str(tmp_path), [str(tmp_path / "b.png")])
    assert len(d) == 1 and d[0]["keep"].endswith("b.png") and d[0]["remove"][0].endswith("a.png")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.api as api
    monkeypatch.setattr(api, "store", JsonStore(str(tmp_path / "db.json")))
    monkeypatch.setattr(api.registry, "output_dir", str(tmp_path / "out"))
    os.makedirs(tmp_path / "out")
    guard._inflight.clear()
    return TestClient(api.app)


def test_routes(client):
    assert "a3_portrait_300dpi" in client.get("/print-sizes").json()
    p = client.post("/projects/from-category", json={"category": "sweet_shop", "business": "Sharma Sweets",
                                                     "price": 1499, "lang": "hi", "digits": "devanagari"}).json()
    assert "₹१,४९९" in [l["text"] for l in p["layers"] if l["type"] == "text"]
    assert "score" in client.get(f"/projects/{p['id']}/check").json()
    assert "applied" in client.post(f"/projects/{p['id']}/fix").json()
    c = client.get(f"/projects/{p['id']}/compare")
    assert c.status_code == 200 and c.content[:4] == b"\x89PNG"
    pr = client.post("/prompts", json={"text": "Diwali sale background", "tags": ["festival"]}).json()
    assert client.get("/prompts", params={"q": "diwali"}).json()[0]["id"] == pr["id"]
    assert client.delete(f"/prompts/{pr['id']}").status_code == 200
    assert client.post("/assets", json={"name": "x", "image_base64": b64(b"junk")}).status_code == 400
    a = client.post("/assets", json={"name": "Diya sticker", "kind": "sticker", "image_base64": b64(png())}).json()
    assert client.get("/assets", params={"q": "diya"}).json()[0]["id"] == a["id"]
    assert client.get(f"/assets/{a['id']}/image").status_code == 200
    assert client.post("/generate/fallback", json={"prompt": "x", "providers": ["nope"]}).status_code == 400
    f = client.post("/generate/fallback", json={"prompt": "x", "providers": ["mock"]}).json()
    assert f["provider_used"] == "mock" and f["fallback_used"] is False
    fm = client.post("/format-in", json={"amount": 1234567, "date": "2026-11-11", "lang": "hi", "digits": "devanagari"}).json()
    assert fm == {"amount": "₹१२,३४,५६७", "date": "११ नवंबर २०२६"}
    assert client.get("/festivals/verified").json()["dates"][0]["source"].startswith("http")
    assert client.get("/jobs").status_code == 200 and client.get("/usage/summary").status_code == 200
    assert client.post("/storage/cleanup").json()["dry_run"] is True


def test_duplicate_request_guard(client):
    body = b'{"prompt": "hello"}'
    guard._inflight[guard.key("/generate", body)] = time.time()
    r = client.post("/generate", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 409
    assert guard.claim("k1") and not guard.claim("k1")
    assert client.post("/generate", json={"prompt": "something else"}).status_code == 200
