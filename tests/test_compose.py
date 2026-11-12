"""Compose pipeline tests — mock provider, no API key, no network."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.compose import (compose_poster, footer_lines, pick_palette,
                              render_footer)
from app.core.prompt_builder import build_prompt
from app.core.registry import ProviderRegistry


@pytest.fixture()
def reg(tmp_path):
    r = ProviderRegistry()
    r.providers = {"mock": r.providers["mock"]}
    r.default_provider = "mock"
    r.features = {k: None for k in r.features}
    r.output_dir = str(tmp_path / "outputs")
    return r


def logo_png():
    buf = io.BytesIO()
    Image.new("RGBA", (80, 40), (20, 60, 140, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_prompt_builder_keeps_user_text_and_style():
    out = build_prompt("Diwali sale poster", "festive", 1080, 1350)
    assert out.startswith("Diwali sale poster")
    assert "festive" in out and "portrait" in out
    with pytest.raises(ValueError):
        build_prompt("   ")


def test_compose_creates_files_with_exact_size(reg):
    out = compose_poster(reg, "Diwali sale", "Sharma Sweets",
                         {"phone": "9876543210", "website": "sharma.in"},
                         logo_png(), "festive", 1080, 1350)
    assert out["success"], out
    final = Image.open(io.BytesIO(out["final_bytes"]))
    assert final.size == (1080, 1350)
    for path in out["files"].values():
        assert __import__("os").path.exists(path)
    assert any("MOCK" in w for w in out["meta"]["warnings"])


def test_empty_fields_are_not_shown():
    lines = [t for t, _ in footer_lines("Shop", {"phone": "123", "email": ""})]
    assert lines == ["Shop", "Call: 123"]


@pytest.mark.parametrize("shape", ["rectangle", "rounded", "wave", "diagonal"])
@pytest.mark.parametrize("pos", ["bottom", "top"])
def test_footer_shapes_and_positions(shape, pos):
    img, fits = render_footer(900, 150, shape, pos, (20, 60, 140), (240, 200, 80),
                              [("Shop", True), ("Call: 123", False)])
    assert img.size == (900, 150) and fits


def test_works_when_provider_cannot_suggest_layout(reg):
    reg.providers["mock"].capabilities = frozenset({"generate_image"})
    out = compose_poster(reg, "poster", "Shop", {}, None, "", 512, 512)
    assert out["success"]
    assert any("rule-based" in w for w in out["meta"]["warnings"])


def test_empty_prompt_fails_cleanly(reg):
    assert compose_poster(reg, "", "Shop")["success"] is False


def test_palette_skips_white_background():
    primary, _ = pick_palette(["#FFFFFF", "#173A70", "#D5AD52"])
    assert primary == (0x17, 0x3A, 0x70)


def test_api_compose_endpoint():
    import base64
    from fastapi.testclient import TestClient
    from app.api import app
    c = TestClient(app)
    c.post("/switch", json={"provider": "mock"})
    r = c.post("/compose", json={"prompt": "test", "business": "Shop",
                                 "phone": "123", "width": 512, "height": 512})
    assert r.status_code == 200
    assert base64.b64decode(r.json()["final_image_base64"]).startswith(b"\x89PNG")


# ---------------------------------------------------------------- new engine
from app.core.colors import build_design_palette, contrast_ratio, hex_to_rgb  # noqa: E402
from app.core.compose import FOOTER_STYLES, draw_headline, prepare_logo  # noqa: E402
from app.core.prompt_builder import build_edit_prompt, closest_aspect_ratio  # noqa: E402


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_artwork_prompt_forbids_text_but_poster_mode_requests_it():
    art = build_prompt("Diwali", mode="artwork")
    poster = build_prompt("Diwali", mode="poster", headline="Happy Diwali")
    assert "no text" in art
    assert '"Happy Diwali"' in poster and "no text" not in poster


def test_edit_prompt_preserves_everything_else():
    assert "Preserve" in build_edit_prompt("make it darker")
    assert closest_aspect_ratio(1080, 1350) == "4:5"
    assert closest_aspect_ratio(1920, 1080) == "16:9"


def test_design_palette_has_roles_and_readable_text():
    logo = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    for x in range(10, 50):
        for y in range(10, 50):
            logo.putpixel((x, y), (20, 60, 140, 255))
    pal = build_design_palette(_png_bytes(logo))
    assert pal["primary"] == "#143C8C" or pal["source"] == "logo"
    assert all(k in pal for k in ("secondary", "accent", "dark", "light", "gradient"))
    assert contrast_ratio(hex_to_rgb(pal["text_on_dark"]), hex_to_rgb(pal["dark"])) >= 4.5


def test_white_background_logo_gets_transparent():
    logo = Image.new("RGB", (80, 80), (255, 255, 255))
    for x in range(20, 60):
        for y in range(20, 60):
            logo.putpixel((x, y), (120, 20, 60))
    out = prepare_logo(logo)
    assert out.size == (40, 40)                  # white border removed, cropped to content


@pytest.mark.parametrize("shape", FOOTER_STYLES)
def test_every_footer_style_renders_with_logo_and_cta(shape):
    logo = Image.new("RGBA", (50, 50), (30, 30, 30, 255))
    img, fits = render_footer(1000, 200, shape, "bottom", (20, 60, 140),
                              (240, 200, 80), [("Shop", True), ("Call: 1", False)],
                              logo, accent=(230, 176, 60), cta="20% OFF")
    assert img.size == (1000, 200) and fits


def test_headline_moves_below_a_top_footer(reg):
    out = compose_poster(reg, "poster", "Shop", {"phone": "1"}, None, "", 800, 1000,
                         "top", headline="Happy Diwali", footer_style="curved")
    assert out["success"] and out["meta"]["headline_drawn"]
    assert out["meta"]["footer"]["position"] == "top"


def test_hindi_headline_renders_without_warning(reg):
    out = compose_poster(reg, "poster", "Shop", {}, None, "", 800, 1000,
                         headline="शुभ दीपावली", subheading="Wishing you light")
    assert out["success"]
    assert not any("Hindi" in w for w in out["meta"]["warnings"])


def test_uploaded_poster_skips_generation(reg):
    reg.providers["mock"].generate_image = lambda **k: (_ for _ in ()).throw(
        AssertionError("must not generate"))
    poster = _png_bytes(Image.new("RGB", (300, 400), (30, 90, 60)))
    out = compose_poster(reg, "", "Shop", {"phone": "1"}, None, "", 600, 800,
                         poster_bytes=poster)
    assert out["success"] and out["meta"]["provider"] == "uploaded"


def test_auto_footer_style_varies_between_designs(reg):
    styles = set()
    for i in range(12):
        out = compose_poster(reg, f"poster {i}", f"Shop {i}", {}, None, "", 400, 500)
        styles.add(out["meta"]["footer"]["shape"])
    assert len(styles) >= 3


def test_explicit_footer_style_wins(reg):
    out = compose_poster(reg, "poster", "Shop", {}, None, "", 400, 500, footer_style="wave")
    assert out["meta"]["footer"]["shape"] == "wave"
