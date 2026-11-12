"""Script to run connection and live tests for all providers with configured API keys."""
import os
import sys
import time
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

def main():
    print("=" * 60)
    print("TESTING PROVIDER CONNECTIONS AND LIVE GENERATION")
    print("=" * 60)

    reg = ProviderRegistry()
    print(f"Registered providers: {list(reg.providers.keys())}\n")

    test_prompt = "a plain red circle on a white background"

    for name, p in reg.providers.items():
        if name == "mock":
            print(f"[{name}] Skipping mock provider.")
            continue
        print(f"\n--- Provider: {name} ({p.display_name}) ---")
        print(f"Model ID: {p.model_id}")
        health = p.health_check()
        print(f"Health check: {health}")

        # Check configuration
        configured = getattr(p, "configured", True)
        if hasattr(p, "api_key") and not p.api_key:
            configured = False
        if not configured:
            print(f"Status: NOT CONFIGURED (missing credentials)")
            continue

        if "generate_image" not in p.capabilities:
            print(f"Status: Does not support generate_image")
            continue

        print(f"Running live test generation (512x512)...")
        start = time.time()
        try:
            img_bytes = p.generate_image(test_prompt, width=512, height=512)
            elapsed = time.time() - start
            out_path = Path(__file__).parent.parent / "outputs" / "live_tests" / f"{name}.png"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            print(f"SUCCESS! Received {len(img_bytes)} bytes in {elapsed:.2f}s. Saved to {out_path}")
        except Exception as e:
            elapsed = time.time() - start
            print(f"FAILED after {elapsed:.2f}s: {e}")

if __name__ == "__main__":
    main()

