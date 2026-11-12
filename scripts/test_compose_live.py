"""Test full compose engine using pollinations_flux and gemini_text."""
import os
import sys
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.registry import ProviderRegistry
from app.core.compose import compose_poster

def main():
    reg = ProviderRegistry()
    print("Testing compose_poster with real providers...")
    img_prov = reg._resolve_feature_provider("generate_image")
    lay_prov = reg._resolve_feature_provider("suggest_layout")
    print("Image provider:", img_prov.name, "(", img_prov.model_id, ")")
    print("Layout provider:", lay_prov.name, "(", lay_prov.model_id, ")")

    out = compose_poster(
        reg,
        prompt="Diwali festival celebration with bright diyas and marigold flowers",
        business="Royal Sweets",
        details={"phone": "+91 98765 43210", "address": "M.G. Road, Bangalore", "cta": "20% OFF ALL SWEETS"},
        headline="शुभ दीपावली",
        subheading="Sweeten your celebrations this Diwali",
        width=1080,
        height=1350,
        footer_style="wave",
        footer_position="bottom"
    )

    if out["success"]:
        print("\nSUCCESS! Poster created:")
        for k, v in out["files"].items():
            print(f"  {k}: {v}")
        print("Meta:", out["meta"])
    else:
        print("\nFAILED:", out.get("error"))

if __name__ == "__main__":
    main()
