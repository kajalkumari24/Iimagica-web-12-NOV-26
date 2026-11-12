"""CLI — same engine as the API, convenient for quick model tests.

Examples:
    python -m app.cli models
    python -m app.cli switch mock
    python -m app.cli generate "Diwali sale poster background, marigold theme"
    python -m app.cli layout frame --business "Sharma Sweets"
    python -m app.cli enhance "poster background for bakery"
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time

from .core.colors import extract_brand_colors
from .core.compose import compose_poster
from .core.registry import ProviderRegistry

registry = ProviderRegistry()


def _run(feature: str, kwargs: dict, save: bool = False) -> int:
    start = time.perf_counter()
    result = registry.run(feature, kwargs)
    elapsed = round((time.perf_counter() - start) * 1000, 1)
    print(f"provider={result.provider} model={result.model_id} "
          f"feature={feature} ok={result.success} time={elapsed}ms")
    if not result.success:
        print(f"ERROR: {result.error}", file=sys.stderr)
        return 1
    if isinstance(result.data, bytes):
        if save:
            out_dir = f"{registry.output_dir}/{feature}"
            import os
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{int(time.time() * 1000)}.png")
            with open(path, "wb") as fh:
                fh.write(result.data)
            print(f"saved: {path}")
        else:
            print(f"[{len(result.data)} bytes of image data]")
    else:
        print(json.dumps(result.data, indent=2, default=str)
              if not isinstance(result.data, str) else result.data)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="iimagica")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("models")

    p_switch_cmd = sub.add_parser("switch")
    p_switch_cmd.add_argument("provider")

    p_gen = sub.add_parser("generate")
    p_gen.add_argument("prompt")
    p_gen.add_argument("--width", type=int, default=1024)
    p_gen.add_argument("--height", type=int, default=1024)
    p_gen.add_argument("--save", action="store_true")

    p_edit = sub.add_parser("edit")
    p_edit.add_argument("prompt")
    p_edit.add_argument("image")
    p_edit.add_argument("--save", action="store_true")

    p_an = sub.add_parser("analyze")
    p_an.add_argument("image")
    p_an.add_argument("--question", default="Describe colors, shapes, style.")

    p_lay = sub.add_parser("layout")
    p_lay.add_argument("kind", choices=["frame", "footer"])
    p_lay.add_argument("--business", required=True)
    p_lay.add_argument("--details", default="{}")

    p_en = sub.add_parser("enhance")
    p_en.add_argument("prompt")
    p_en.add_argument("--context", default="")

    p_col = sub.add_parser("colors")
    p_col.add_argument("image")

    p_cmp = sub.add_parser("compose", help="prompt -> poster + frame + footer")
    p_cmp.add_argument("prompt")
    p_cmp.add_argument("--business", default="")
    p_cmp.add_argument("--style", default="")
    p_cmp.add_argument("--logo", default=None, help="path to logo image")
    p_cmp.add_argument("--width", type=int, default=1024)
    p_cmp.add_argument("--height", type=int, default=1024)
    p_cmp.add_argument("--footer-position", default="bottom",
                       choices=["bottom", "top"])
    for field_name in ("phone", "whatsapp", "email", "website", "address", "cta"):
        p_cmp.add_argument(f"--{field_name}", default="")

    args = parser.parse_args()

    if args.command == "models":
        print(json.dumps(registry.list_models(), indent=2))
        return 0
    if args.command == "switch":
        print(json.dumps(registry.switch_default(args.provider), indent=2))
        return 0
    if args.command == "generate":
        return _run("generate_image",
                    {"prompt": args.prompt, "width": args.width,
                     "height": args.height}, save=args.save)
    if args.command == "edit":
        with open(args.image, "rb") as fh:
            image_bytes = fh.read()
        return _run("edit_image",
                    {"image_bytes": image_bytes, "prompt": args.prompt},
                    save=args.save)
    if args.command == "analyze":
        with open(args.image, "rb") as fh:
            image_bytes = fh.read()
        return _run("analyze_image",
                    {"image_bytes": image_bytes, "question": args.question})
    if args.command == "layout":
        return _run("suggest_layout",
                    {"kind": args.kind, "business": args.business,
                     "details": json.loads(args.details)})
    if args.command == "enhance":
        return _run("enhance_prompt",
                    {"prompt": args.prompt, "context": args.context})
    if args.command == "colors":
        with open(args.image, "rb") as fh:
            print(json.dumps(extract_brand_colors(fh.read()), indent=2))
        return 0
    if args.command == "compose":
        logo = None
        if args.logo:
            with open(args.logo, "rb") as fh:
                logo = fh.read()
        details = {k: getattr(args, k) for k in
                   ("phone", "whatsapp", "email", "website", "address", "cta")}
        out = compose_poster(registry, args.prompt, args.business, details,
                             logo, args.style, args.width, args.height,
                             args.footer_position)
        if not out["success"]:
            print(f"ERROR: {out['error']}", file=sys.stderr)
            return 1
        print(json.dumps({"files": out["files"], "meta": out["meta"]}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
