"""Tests for remove-bg, upscale, model-lab compare/ratings and gallery."""
from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import api
from app.core.extras import remove_background, upscale
from app.core.store import JsonStore


def png(color, size=(40, 40), box=None, box_color=(200, 0, 0)):
    img = Image.new("RGB", size, color)
    if box:
        img.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), box_color), box[:2])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api.registry, "output_dir", str(tmp_path))
    monkeypatch.setattr(api, "store", JsonStore(str(tmp_path / "db.json")))
    return TestClient(api.app)


def test_remove_background_keeps_subject():
    out = Image.open(io.BytesIO(remove_background(png((255, 255, 255), box=(15, 15, 25, 25)))))
    assert out.mode == "RGBA"
    assert out.getpixel((1, 1))[3] < 30      # border -> transparent
    assert out.getpixel((20, 20))[3] > 225   # subject stays opaque


def test_upscale_and_bounds():
    out = Image.open(io.BytesIO(upscale(png((9, 9, 9)), 3)))
    assert out.size == (120, 120)
    with pytest.raises(ValueError):
        upscale(png((9, 9, 9)), 9)


def test_compare_rate_leaderboard(client):
    r = client.post("/compare", json={"prompt": "diwali", "providers": ["mock"]})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["results"][0]["success"]
    ok = client.post(f"/compare/{cid}/rate",
                     json={"provider": "mock", "scores": {"visual_quality": 4, "composition": 5}})
    assert ok.status_code == 200
    bad = client.post(f"/compare/{cid}/rate", json={"provider": "mock", "scores": {"x": 3}})
    assert bad.status_code == 400
    row = client.get("/leaderboard").json()[0]
    assert row["provider"] == "mock" and row["overall"] == 4.5
    assert len(client.get("/compare/history").json()) == 1
    assert client.post("/compare", json={"prompt": "a", "providers": ["nope"]}).status_code == 400


def test_gallery_flow(client):
    b64 = base64.b64encode(png((1, 2, 3))).decode()
    rec = client.post("/gallery", json={"image_base64": b64, "title": "Diwali Sale",
                                        "tags": ["festival"]}).json()
    assert len(client.get("/gallery", params={"q": "diwali"}).json()) == 1
    assert client.get("/gallery", params={"q": "holi"}).json() == []
    assert client.post(f"/gallery/{rec['id']}/favorite").json()["favorite"] is True
    assert len(client.get("/gallery", params={"favorite": True}).json()) == 1
    assert client.delete(f"/gallery/{rec['id']}").status_code == 200
    assert client.delete(f"/gallery/{rec['id']}").status_code == 404
