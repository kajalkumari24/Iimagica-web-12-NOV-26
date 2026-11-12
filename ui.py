"""Simple browser UI: type a prompt -> poster + frame + footer.

Run:  python ui.py      then open http://127.0.0.1:7860
Uses the same compose engine as the API and CLI, so the selected provider
(mock / pollinations_flux / stability / ...) is whatever you pick in the dropdown below.
"""
from __future__ import annotations

import os

import gradio as gr

from app.core.compose import FOOTER_STYLES, compose_poster
from app.core.prompt_builder import STYLES
from app.core.registry import ProviderRegistry

registry = ProviderRegistry()

SIZES = {
    "Instagram portrait 1080x1350": (1080, 1350),
    "Square 1024x1024": (1024, 1024),
    "Instagram square 1080x1080": (1080, 1080),
    "Portrait 1024x1536": (1024, 1536),
    "Landscape 1536x1024": (1536, 1024),
}


def run(prompt, business, style, size, logo_path, phone, whatsapp, email,
        website, address, cta, footer_position, provider, headline="",
        subheading="", footer_style="auto", poster_path=None, num_variations=1):
    if not (prompt or "").strip():
        return None, [], "Please enter a prompt.", None
    # in-memory only: does NOT rewrite config.yaml
    registry.default_provider = provider
    logo = None
    if logo_path:
        with open(logo_path, "rb") as fh:
            logo = fh.read()
    width, height = SIZES[size]
    details = {"phone": phone, "whatsapp": whatsapp, "email": email,
               "website": website, "address": address, "cta": cta}
    poster = None
    if poster_path:
        with open(poster_path, "rb") as fh:
            poster = fh.read()

    gallery_images = []
    all_files = []
    notes = []
    count = max(1, min(4, int(num_variations or 1)))

    for v in range(count):
        out = compose_poster(registry, prompt, business or "", details, logo,
                             style if style != "(none)" else "", width, height,
                             footer_position.lower(), headline=headline or "",
                             subheading=subheading or "", footer_style=footer_style,
                             poster_bytes=poster)
        if out["success"]:
            gallery_images.append(out["files"]["final"])
            all_files.extend(list(out["files"].values()))
            if v == 0:
                meta = out["meta"]
                notes = [f"Model: {meta['provider']} / {meta['model_id']}",
                         f"Palette: {meta.get('palette', {}).get('primary', '')} / {meta.get('palette', {}).get('accent', '')}",
                         f"Saved in: {os.path.dirname(out['files']['final'])}"]
                notes += [f"Warning: {w}" for w in meta.get("warnings", [])]
        else:
            if not gallery_images:
                return None, [], f"Error: {out['error']}", None

    first = gallery_images[0] if gallery_images else None
    return first, gallery_images, "\n".join(notes), list(dict.fromkeys(all_files))


with gr.Blocks(title="iimagica") as demo:
    gr.Markdown("# iimagica — AI Poster, Frame and Footer Studio")
    with gr.Row():
        with gr.Column(scale=1):
            prompt = gr.Textbox(label="Poster prompt", lines=3,
                                placeholder="Diwali sale poster with glowing diyas and marigolds",
                                value="Diwali sale poster with diyas and marigolds")
            business = gr.Textbox(label="Business name", placeholder="Sharma Sweets", value="Sharma Sweets")
            headline = gr.Textbox(label="Headline (English or Hindi, drawn exactly)",
                                  placeholder="शुभ दीपावली", value="शुभ दीपावली")
            subheading = gr.Textbox(label="Subheading", placeholder="Special Festive Sweets & Dry Fruit Hampers",
                                    value="Special Festive Sweets & Dry Fruit Hampers")
            with gr.Row():
                style = gr.Dropdown(["(none)"] + [s.title() for s in STYLES],
                                    value="Festive", label="Style")
                size = gr.Dropdown(list(SIZES), value="Instagram portrait 1080x1350",
                                   label="Size")
            with gr.Row():
                num_variations = gr.Radio([1, 2, 4], value=1, label="Variations to generate")
                footer_pos = gr.Radio(["Bottom", "Top"], value="Bottom", label="Footer position")
            logo = gr.Image(label="Logo (optional)", type="filepath")
            poster_up = gr.Image(label="Use my own poster background instead of AI generation (optional)",
                                 type="filepath")
            with gr.Row():
                phone = gr.Textbox(label="Phone", placeholder="+91 98765 43210")
                whatsapp = gr.Textbox(label="WhatsApp", placeholder="+91 98765 43210")
            with gr.Row():
                email = gr.Textbox(label="Email", placeholder="contact@sharmasweets.in")
                website = gr.Textbox(label="Website", placeholder="www.sharmasweets.in")
            address = gr.Textbox(label="Address", placeholder="12 M.G. Road, Bangalore")
            cta = gr.Textbox(label="Call-to-action (e.g. 20% off)", placeholder="20% OFF ALL SWEETS", value="20% OFF ALL SWEETS")
            with gr.Row():
                footer_style = gr.Dropdown(["auto"] + list(FOOTER_STYLES), value="auto",
                                           label="Footer design")
                provider = gr.Dropdown([p for p in registry.providers if p not in ("flux", "gemini", "gemini_lite")],
                                       value=registry.default_provider,
                                       label="Model / Provider (Free-Tier)")
            go = gr.Button("Generate Poster", variant="primary", size="lg")
        with gr.Column(scale=1):
            result = gr.Image(label="Final Poster (Latest)")
            gallery = gr.Gallery(label="Poster Variations / Concepts", columns=2, height="auto")
            info = gr.Textbox(label="Details and warnings", lines=4)
            files = gr.File(label="Download files", file_count="multiple")

    go.click(run, [prompt, business, style, size, logo, phone, whatsapp, email,
                   website, address, cta, footer_pos, provider, headline,
                   subheading, footer_style, poster_up, num_variations],
             [result, gallery, info, files])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
