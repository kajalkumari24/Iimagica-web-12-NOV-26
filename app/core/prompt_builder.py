"""Prompt builder: turns a short request into a detailed art-directed prompt.

Works offline (no LLM). Two modes, so the old "no text" rule no longer
contradicts requests that need text:

  mode="artwork"  - image model paints art only; exact headline / footer text
                    is added afterwards by the typography engine in compose.py
                    (reliable spelling, works for Hindi). DEFAULT for business
                    posters.
  mode="poster"   - image model is asked to render the given text itself, with
                    the exact wording quoted.
  mode="edit"     - change an existing image, preserve everything else.

The user's own words are always kept verbatim at the start.
"""
from __future__ import annotations

STYLES: dict[str, str] = {
    "realistic": "photorealistic, natural lighting, sharp detail, shallow depth of field",
    "traditional indian": "traditional Indian decorative art, rich warm colors, ornate patterns, "
                          "intricate rangoli and paisley motifs",
    "modern": "modern graphic design, clean geometric shapes, bold contemporary look",
    "minimalist": "minimalist, generous negative space, soft muted palette, refined simplicity",
    "3d": "3D rendered, soft studio shadows, depth, glossy and metallic materials",
    "cartoon": "friendly cartoon illustration, bright flat colors, clean outlines",
    "artistic": "artistic painterly style, expressive brush texture, rich color blending",
    "corporate": "professional corporate look, clean and trustworthy, subtle gradients",
    "festive": "festive celebration mood, warm golden lighting, decorative elements, glowing accents",
    "luxury": "luxury premium look, deep rich background, gold metallic accents, elegant glow",
}

# Generic art direction (not tied to any one festival or business type).
ART_DIRECTION = (
    "Art-directed professional advertising poster background with a clear focal point, "
    "strong visual hierarchy, layered depth (foreground, midground, background), "
    "rich textures, intentional cinematic lighting with soft glow and highlights, "
    "harmonious limited color palette, and balanced composition"
)


def _orientation(width: int, height: int) -> str:
    if abs(width - height) <= 0.05 * max(width, height):
        return "square"
    return "portrait" if height > width else "landscape"


def closest_aspect_ratio(width: int, height: int) -> str:
    """Nearest aspect ratio the Gemini image API accepts."""
    options = {"1:1": 1.0, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3,
               "4:5": 0.8, "5:4": 1.25, "9:16": 9 / 16, "16:9": 16 / 9,
               "21:9": 21 / 9}
    target = width / height
    return min(options, key=lambda k: abs(options[k] - target))


def build_prompt(prompt: str, style: str = "", width: int = 1024,
                 height: int = 1024, reserve_footer: bool = True, *,
                 mode: str = "artwork", headline: str = "",
                 subheading: str = "", palette: list[str] | None = None,
                 reference: bool = False, reserve_headline: bool = False) -> str:
    """Build the final generation prompt.

    reserve_footer / reserve_headline keep calm areas in the artwork for the
    footer and for headline text that compose.py draws on top.
    """
    prompt = (prompt or "").strip().rstrip(".")
    if not prompt:
        raise ValueError("Prompt is empty.")
    if mode == "edit":
        return build_edit_prompt(prompt)

    parts = [prompt]
    style_text = STYLES.get((style or "").strip().lower())
    if style_text:
        parts.append(style_text)
    parts.append(ART_DIRECTION)
    parts.append(f"{_orientation(width, height)} composition")
    if palette:
        parts.append("dominant color palette: " + ", ".join(palette[:3]))
    if reference:
        parts.append("use the supplied reference image for subject, style and brand "
                     "identity; do not alter logos or lettering that appear in it")

    layout_notes = []
    if reserve_headline:
        layout_notes.append("keep the upper third calm and uncluttered for a headline")
    if reserve_footer:
        layout_notes.append("keep the bottom 15% calm and uncluttered for a footer")
    if layout_notes:
        parts.append("; ".join(layout_notes))

    if mode == "poster":
        texts = []
        if headline.strip():
            texts.append(f'headline text exactly: "{headline.strip()}"')
        if subheading.strip():
            texts.append(f'subheading text exactly: "{subheading.strip()}"')
        if texts:
            parts.append("render this text with perfect spelling in elegant, highly "
                         "legible typography - " + "; ".join(texts))
        parts.append("no watermarks, no extra or invented text")
    else:  # artwork
        parts.append("no text, no letters, no numbers, no logos, no watermarks")
    return ". ".join(parts) + "."


def build_edit_prompt(instruction: str, preserve: str = "") -> str:
    """Prompt for editing an existing image (image-to-image)."""
    instruction = (instruction or "").strip().rstrip(".")
    if not instruction:
        raise ValueError("Edit instruction is empty.")
    keep = preserve.strip() or ("all unrelated elements, the composition, subjects, "
                                "logos, text and visual details")
    return (f"Edit the supplied image: {instruction}. "
            f"Preserve {keep}. Change only what was asked.")
