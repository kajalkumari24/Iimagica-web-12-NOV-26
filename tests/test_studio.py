"""Tests for studio logic, jobs/retry, store collections. No fixtures needed."""
from __future__ import annotations

import base64
import datetime as dt
import io
import os
import tempfile

from PIL import Image

from app.core import studio as S
from app.core.jobs import Jobs, call
from app.core.store import JsonStore


def png(color=(200, 30, 30), size=(60, 40)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


def test_export_formats_and_sizes():
    img = Image.new("RGB", (100, 50), "red")
    for fmt in ("PNG", "JPG", "PDF"):
        assert S.to_bytes(img, fmt)
    out = S.resize_to(img, 1080, 1920)
    assert out.size == (1080, 1920)
    assert S.expand(img, left=10, top=20).size == (110, 70)


def test_layer_ops_lock_reorder_duplicate_undo():
    p = S.new_project("t", 400, 400, [])
    a = S.new_layer(type="rect", name="a")
    S.commit(p, S.apply_op(S.current(p), {"op": "add", "layer": a}))
    S.commit(p, S.apply_op(S.current(p), {"op": "add", "layer": {"type": "text", "text": "Hi"}}))
    aid = S.current(p)[0]["id"]
    S.commit(p, S.apply_op(S.current(p), {"op": "duplicate", "id": aid}))
    assert len(S.current(p)) == 3
    S.commit(p, S.apply_op(S.current(p), {"op": "reorder", "id": aid, "index": 2}))
    assert S.current(p)[2]["id"] == aid
    S.commit(p, S.apply_op(S.current(p), {"op": "lock", "id": aid}))
    try:
        S.apply_op(S.current(p), {"op": "delete", "id": aid})
        raise AssertionError("locked layer deleted")
    except PermissionError:
        pass
    S.undo(p)
    S.undo(p)
    assert len(S.current(p)) == 3
    S.redo(p)
    assert S.current(p)[2]["locked"] is False
    S.commit(p, S.current(p))          # new edit drops redo history
    assert p["cursor"] == len(p["versions"]) - 1


def test_render_templates_and_hindi():
    for name in S.TEMPLATES:
        layers = S.template_layers(name, 540, 675, {"name": "Sharma Sweets", "colors": ["#B71C1C", "#FFC107"]})
        assert S.render(540, 675, layers).size == (540, 675)
    L = [S.new_layer(type="text", text="दिवाली की शुभकामनाएँ", w=400, h=100, shadow=True, rotation=5)]
    assert S.render(540, 675, L).size == (540, 675)


def test_analysis():
    img = Image.new("RGB", (200, 200), (250, 220, 120))
    ev = S.evaluate(img)
    assert 0 <= ev["score"] <= 100 and ev["best_text_region"]["text_color"] in ("#ffffff", "#000000")
    assert S.brand_check(img, ["#FADC78"])["pass"] is True
    assert S.brand_check(img, ["#0000FF"])["pass"] is False


def test_festivals_captions_languages():
    today = dt.date(2026, 11, 10)
    names = [f["name"] for f in S.festivals(today, 10)]
    assert "Children's Day" in names
    f = {x["name"]: x for x in S.festivals(today, 45)}
    assert f["Diwali"]["date_varies"] is True and f["Christmas"]["days_left"] == 45
    assert "Gujarat" not in str(S.festivals(today, 45, "KL"))
    assert "दिवाली" in S.greeting("Diwali", "hi")
    assert "#Diwali" in S.captions("Diwali", "Sharma Sweets")[0]


def test_retry_usage_errors_and_jobs():
    d = tempfile.mkdtemp()
    store = JsonStore(os.path.join(d, "db.json"))

    class P:
        model_id = "x"
        n = 0

        def generate_image(self, **kw):
            P.n += 1
            if P.n < 3:
                raise RuntimeError("quota")
            return b"img"

    class R:
        providers = {"p": P()}
        config = {"providers": {"p": {"cost_per_image": 0.04}}}

    o = call(R, store, "p", "generate_image", retries=2, backoff=0, prompt="a")
    assert o["success"] and o["attempts"] == 3 and o["est_cost"] == 0.04
    assert len(store.all("errors")) == 2 and store.usage_today()["p"] == 3
    j = Jobs()
    jid = j.start(3, lambda: iter([{"i": i} for i in range(3)]), wait=True)
    assert j.get(jid)["status"] == "done" and j.get(jid)["done"] == 3


def test_collections_and_backup():
    d = tempfile.mkdtemp()
    s = JsonStore(os.path.join(d, "db.json"))
    r = s.put("brands", {"name": "A", "colors": ["#fff"]})
    r["name"] = "B"
    s.put("brands", r)
    assert [b["name"] for b in s.all("brands")] == ["B"]
    path = S.backup(d)
    assert s.remove("brands", r["id"]) and s.all("brands") == []
    assert S.restore(d, os.path.basename(path)) >= 1
    assert s.all("brands")[0]["name"] == "B"
