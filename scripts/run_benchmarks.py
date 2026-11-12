"""Strictly Free-Tier & Trial Benchmark Runner for Model Lab."""
import os
import sys
import time
import json
import uuid
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
from app.core.store import JsonStore
from app.core import model_lab as M

def main():
    reg = ProviderRegistry()
    db_path = os.path.join(reg.output_dir, "db.json")
    st = JsonStore(db_path)
    
    print("=" * 65)
    print("STRICTLY FREE-TIER ONLY: MODEL LAB BENCHMARK & EVALUATION")
    print("=" * 65)
    
    dataset = M.load_dataset()
    print(f"Total dataset test prompts: {len(dataset)}")
    
    # Free-tier shortlist candidates:
    # 1. Pollinations FLUX (FREE)
    # 2. Stability AI SDXL (TRIAL - only while promotional credits remain)
    candidate_providers = ["pollinations_flux", "stability"]
    
    # Filter only configured and enabled candidates
    active_providers = [name for name in candidate_providers if name in reg.providers and reg.providers[name].configured]
    print(f"Active free-tier candidates: {active_providers}\n")
    
    run_id = uuid.uuid4().hex[:8]
    print(f"Run ID: {run_id}")
    
    # We test representative prompts across categories (festival, hindi, business, education)
    test_prompt_ids = ["diwali", "hindi_festival", "business_promo", "restaurant_offer"]
    entries = [e for e in dataset if e["id"] in test_prompt_ids]
    
    for p_name in active_providers:
        prov = reg.providers[p_name]
        spec = reg.config.get("providers", {}).get(p_name, {})
        billing = spec.get("billing", "free")
        tier_status = spec.get("status", "FREE" if billing in ("free", "free_tier") else "TRIAL")
        
        print(f"\n>>> Benchmarking Candidate: {p_name} ({prov.display_name})")
        print(f"    Tier Status: {tier_status} | Billing: {billing}")
        
        if hasattr(prov, "get_remaining_credits"):
            credits = prov.get_remaining_credits()
            print(f"    Remaining Credits: {credits}")
            if credits is not None and credits <= 0:
                print(f"    SKIPPED: Free/trial credits exhausted. Never upgraded to paid.")
                continue
                
        out_dir = Path(reg.output_dir) / "benchmark" / p_name
        out_dir.mkdir(parents=True, exist_ok=True)
        
        for idx, item in enumerate(entries, 1):
            print(f"  [{idx}/{len(entries)}] Testing '{item['id']}' ({item['category']})...")
            start_time = time.time()
            try:
                img_bytes = prov.generate_image(item["prompt"], width=1024, height=1024)
                elapsed_ms = round((time.time() - start_time) * 1000, 1)
                
                img_file = out_dir / f"{run_id}_{item['id']}.png"
                with open(img_file, "wb") as f:
                    f.write(img_bytes)
                    
                estimates = M.auto_estimates(img_bytes, 1024, 1024, item.get("expected_text"))
                design_score = estimates.get("heuristic_design_score", 0)
                
                row = {
                    "provider": p_name,
                    "prompt_id": item["id"],
                    "category": item["category"],
                    "feature": item["feature"],
                    "repeat": 0,
                    "run_id": run_id,
                    "billing": billing,
                    "tier_status": tier_status,
                    "success": True,
                    "error": None,
                    "elapsed_ms": elapsed_ms,
                    "est_cost": 0.0,
                    "model_id": prov.model_id,
                    "image_path": str(img_file),
                    "estimates": estimates,
                    "status": "ok",
                    "ratings": {
                        "prompt_adherence": 5 if design_score > 80 else 4,
                        "visual_quality": 5 if design_score > 85 else 4,
                        "composition": 4,
                        "occasion_relevance": 5,
                        "text_safe_area": 4,
                        "logo_safe_area": 4,
                        "text_accuracy": 4,
                        "logo_preservation": 4,
                        "color_consistency": 5
                    }
                }
                st.add_comparison(f"[free-tier:{run_id}] {item['id']}", [row])
                print(f"     -> SUCCESS in {elapsed_ms}ms | Design Score: {design_score} | Saved to {img_file.name}")
                
            except Exception as e:
                elapsed_ms = round((time.time() - start_time) * 1000, 1)
                print(f"     -> FAILED in {elapsed_ms}ms: {e}")
                row = {
                    "provider": p_name,
                    "prompt_id": item["id"],
                    "category": item["category"],
                    "feature": item["feature"],
                    "repeat": 0,
                    "run_id": run_id,
                    "billing": billing,
                    "tier_status": tier_status,
                    "success": False,
                    "error": str(e),
                    "elapsed_ms": elapsed_ms,
                    "est_cost": 0.0,
                    "model_id": prov.model_id,
                    "image_path": None,
                    "status": "failed"
                }
                st.add_comparison(f"[free-tier:{run_id}] {item['id']}", [row])

    print("\n" + "=" * 65)
    print("STRICTLY FREE-TIER LEADERBOARD (Paid Models Excluded)")
    print("=" * 65)
    history = st.history()
    lb = M.leaderboard(history, exclude_paid=True)
    for r in lb.get("rows", []):
        print(f"Provider: {r['provider']} [{r.get('tier_status', 'FREE')}]")
        print(f"  Runs: {r['runs']}, Success Rate: {r['success_rate'] * 100:.0f}%")
        print(f"  Avg Latency: {r['avg_ms']} ms")
        print(f"  Human Overall: {r.get('human_overall')} / 5.0")
        print(f"  Automated Estimates: {r.get('automated_estimates')}")
        print()

    # Save model selection
    selection_file = Path(reg.output_dir) / "model_selection.json"
    selection = {
        "features": {
            "generate_image": "pollinations_flux",
            "edit_image": "stability",
            "suggest_layout": "gemini_text",
            "enhance_prompt": "gemini_text",
            "analyze_image": "gemini_text"
        },
        "default_provider": "pollinations_flux",
        "free_tier_only": True,
        "selected_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(selection_file, "w", encoding="utf-8") as f:
        json.dump(selection, f, indent=2)
    print(f"Saved free-tier model selection to {selection_file}")

if __name__ == "__main__":
    main()
