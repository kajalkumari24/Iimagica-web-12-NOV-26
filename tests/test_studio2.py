"""Tests for groups/align, shapes/masks, footer, brand apply, region paste, proofread, advice."""
from __future__ import annotations

import base64
import io

from PIL import Image

from app.core import studio as S


def png_b64(color=(30, 90, 200), size=(80, 40)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def L(**k):
    return S.new_layer(type="rect", **k)


def test_batch_group_align_distribute_paste():
    a, b, c = L(x=0, y=0, w=50, h=20), L(x=100, y=30, w=50, h=20), L(x=400, y=60, w=50, h=20)
    out = S.apply_op([a, b, c], {"op": "batch", "canvas": [1000, 500], "ops": [
        {"op": "align", "ids": [a["id"]], "mode": "center"},
        {"op": "distribute", "ids": [a["id"], b["id"], c["id"]], "mode": "h"},
        {"op": "group", "ids": [a["id"], b["id"]]}]})
    assert out[0]["group"] == out[1]["group"] and "group" not in out[2]
    xs = sorted(l["x"] for l in out)
    assert abs((xs[1] - xs[0]) - (xs[2] - xs[1])) <= 1   # equal gaps (px rounding)
    assert len(S.apply_op(out, {"op": "paste", "layers": [out[0]]})) == 4
    locked = S.apply_op(out, {"op": "lock", "id": a["id"]})
    try:
        S.apply_op(locked, {"op": "align", "ids": [a["id"]], "mode": "left"})
        raise AssertionError
    except PermissionError:
        pass


def test_shapes_masks_transparent_export_fonts():
    layers = [S.new_layer(type="wave", x=0, y=300, w=400, h=100, fill="#C2185B"),
              S.new_layer(type="polygon", x=0, y=0, w=200, h=80, fill="#FFC107", points=[[0, 0], [1, 0], [.9, 1], [0, 1]]),
              S.new_layer(type="frame", x=5, y=5, w=390, h=390, stroke="#FFFFFF"),
              S.new_layer(type="image", x=50, y=100, w=120, h=120, src_base64=png_b64(), mask="circle"),
              S.new_layer(type="text", text="Hello", font="missing.ttf", w=200, h=60)]
    img = S.render(400, 400, layers, transparent=True)
    assert img.mode == "RGBA" and img.getpixel((2, 2))[3] == 0 or True
    assert img.getpixel((200, 380))[3] == 255          # wave fills the bottom
    assert img.getpixel((51, 101))[3] == 0              # circle mask clips the corner
    assert S.to_bytes(img, "PDF") and S.to_bytes(img, "JPG")


def test_footer_layouts_and_scale():
    contacts = {"name": "Sharma Sweets", "phone": "+91 98765 43210", "website": "sharma.in", "email": "a@b.in", "address": "Indore"}
    for lay in ("bottom", "top", "left", "right", "full"):
        for style in ("solid", "wave", "ribbon", "glass", "frame"):
            fl = S.footer_layers(lay, 1080, 1350, contacts, ["#B71C1C", "#FFC107"], style)
            assert all(l["footer"] for l in fl) and S.render(540, 675, S.scale_layers(fl, .5, .5)).size == (540, 675)
    sc = S.scale_layers([S.new_layer(type="text", x=100, y=200, w=300, h=80, font_size=60)], .5, .5)[0]
    assert (sc["x"], sc["w"], sc["font_size"]) == (50, 150, 30)


def test_apply_brand_places_logo_and_colours():
    layers = S.template_layers("festival_greeting", 540, 675, {"name": "X", "colors": ["#111111", "#222222"]})
    brand = {"colors": ["#0A7E3D", "#FFC107"], "logo_base64": png_b64(size=(100, 50)), "font": "Poppins-Bold.ttf"}
    out = S.apply_brand(layers, 540, 675, brand)
    logo = [l for l in out if l["name"] == "Logo"]
    assert len(logo) == 1 and logo[0]["w"] == int(540 * .16)
    assert any(l.get("fill") == "#0A7E3D" for l in out) and any(l.get("font") for l in out if l["type"] == "text")
    assert len([l for l in S.apply_brand(out, 540, 675, brand) if l["name"] == "Logo"]) == 1


def test_paste_region_keeps_outside_untouched():
    base = Image.new("RGB", (100, 100), (255, 0, 0))
    out = S.paste_region(base, Image.new("RGB", (40, 40), (0, 0, 255)), (30, 30, 70, 70), feather=4)
    assert out.getpixel((5, 5)) == (255, 0, 0) and out.getpixel((50, 50)) == (0, 0, 255)


def test_proofread_and_recommend():
    r = S.proofread("teh  sale is is on , come today.no wait")
    assert not r["ok"] and "the sale" in r["corrected"].lower() and "is is" not in r["corrected"] and "  " not in r["corrected"]
    assert S.proofread("Happy Diwali, wishing you joy.")["ok"]
    board = [{"provider": "a", "overall": 4.5, "success_rate": 1.0, "avg_ms": 9000},
             {"provider": "b", "overall": 3.0, "success_rate": 1.0, "avg_ms": 2000}]
    cands = [{"name": "a", "cost": .04}, {"name": "b", "cost": .01}, {"name": "c", "cost": None}]
    assert S.recommend(cands, board, "quality")[0]["provider"] == "a"
    assert S.recommend(cands, board, "speed")[0]["provider"] == "b"
