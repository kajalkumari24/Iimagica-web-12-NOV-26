"""Model Lab: fixed dataset, spend/quota policy, automated estimates, leaderboard. Pure functions (no I/O except the dataset)."""
from __future__ import annotations

import difflib
import json
import os

import numpy as np

from . import studio as S

DATASET = os.path.join(os.path.dirname(__file__), "..", "..", "benchmark_data", "prompts", "poster_prompts.json")
FREE = {"free", "free_tier", "trial"}
QUOTA_WORDS = ("429", "quota", "resource_exhausted", "rate limit", "rate-limit", "too many requests", "credit", "insufficient", "free_limit", "free limit")


def load_dataset() -> list:
    with open(DATASET, encoding="utf-8") as fh:
        return json.load(fh)["prompts"]


def select_entries(ids=None, categories=None) -> list:
    return [e for e in load_dataset() if (not ids or e["id"] in ids) and (not categories or e["category"] in categories)]


def billing_gate(spec: dict, name: str, approve: set, budget: float):
    """Enforces strictly free-tier only: rejects paid models, supports FREE and TRIAL."""
    b = str(spec.get("billing", "unknown")).lower()
    if b in ("paid", "credit"):
        return False, f"{name} is a paid-only provider. iImagica is strictly free-tier only."
    if b in FREE:
        return True, ""
    if name not in approve:
        return False, f"{name} billing is '{b}'. Excluded from free-tier testing."
    return True, ""


def spend_ok(spec: dict, spent: float, budget: float) -> bool:
    if spec.get("billing", "unknown") in FREE:
        return True
    return spent + float(spec.get("cost_per_image") or 0) <= budget


def is_quota_error(msg: str | None) -> bool:
    return bool(msg) and any(w in msg.lower() for w in QUOTA_WORDS)


def ocr_similarity(img, expected):
    """0-1 text match via OCR if pytesseract + tesseract are installed, else None. An estimate, not proof."""
    want = " ".join(" ".join(expected or []).lower().split())
    if not want:
        return None
    try:
        import pytesseract
        lang = "eng+hin" if any("\u0900" <= ch <= "\u097f" for ch in want) else "eng"
        got = " ".join(pytesseract.image_to_string(img, lang=lang).lower().split())
    except Exception:  # noqa: BLE001
        return None
    return round(difflib.SequenceMatcher(None, want, got).ratio(), 2)


def auto_estimates(data: bytes, width: int, height: int, expected_text=None) -> dict:
    """Measurable, automated ESTIMATES. They never replace human ratings."""
    img = S.load(data)
    est = {"kind": "automated_estimate", "size": [img.width, img.height],
           "aspect_ok": abs(img.width / img.height - width / height) <= .02 * (width / height),
           "blank": float(np.asarray(img.convert("L"), float).std()) < 8,
           "text_similarity": ocr_similarity(img, expected_text), "heuristic_design_score": None}
    try:
        est["heuristic_design_score"] = S.evaluate(img)["score"]
    except Exception:  # noqa: BLE001
        pass
    return est


RANKS = {"overall": ("human_overall", True), "text_accuracy": ("text_accuracy", True),
         "prompt_adherence": ("prompt_adherence", True), "logo_preservation": ("logo_preservation", True),
         "visual_quality": ("visual_quality", True), "speed": ("avg_ms", False),
         "cost": ("cost_per_success", False), "reliability": ("success_rate", True)}


def _avg(v):
    return round(sum(v) / len(v), 2) if v else None


def leaderboard(history: list, category: str | None = None, rank_by: str = "overall", exclude_paid: bool = True) -> dict:
    agg = {}
    for c in history:
        for r in c["results"]:
            if exclude_paid and (r.get("billing") == "paid" or r.get("tier_status") == "PAID"):
                continue
            if category and r.get("category") != category:
                continue
            a = agg.setdefault(r["provider"], {"runs": 0, "ok": 0, "ms": [], "cost": [], "sc": {}, "auto": {}, "cats": set(), "tier_status": r.get("tier_status", "FREE")})
            a["runs"] += 1
            a["ok"] += bool(r["success"])
            a["cats"].add(r.get("category"))
            if r["success"] and r.get("elapsed_ms") is not None:
                a["ms"].append(r["elapsed_ms"])
            if r["success"] and r.get("est_cost") is not None:
                a["cost"].append(r["est_cost"])
            for k, v in (r.get("ratings") or {}).items():
                a["sc"].setdefault(k, []).append(v)
            for k in ("heuristic_design_score", "text_similarity"):
                v = (r.get("estimates") or {}).get(k)
                if v is not None:
                    a["auto"].setdefault(k, []).append(v)
    rows = []
    for name, a in agg.items():
        human = {k: _avg(v) for k, v in a["sc"].items()}
        row = {"provider": name, "runs": a["runs"], "success_rate": round(a["ok"] / a["runs"], 2), "avg_ms": _avg(a["ms"]),
               "tier_status": a.get("tier_status", "FREE"),
               "cost_per_success": round(sum(a["cost"]) / a["ok"], 4) if a["cost"] and a["ok"] else None,
               "human_ratings": human, "human_overall": _avg(list(human.values())),
               "automated_estimates": {k: _avg(v) for k, v in a["auto"].items()}}
        row.update({k: v for k, v in human.items() if k in RANKS})
        rows.append(row)
    key, desc = RANKS.get(rank_by, RANKS["overall"])
    rows.sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0) if desc else (r.get(key) or 0)))
    return {"rank_by": rank_by, "category": category, "rows": rows,
            "note": "Rankings strictly exclude paid models. Ratings show FREE and TRIAL models only."}


def winners(history: list) -> dict:
    cats = {r.get("category") for c in history for r in c["results"]} - {None}
    out = {}
    for cat in sorted(cats):
        rows = leaderboard(history, cat)["rows"]
        if rows:
            out[cat] = {"provider": rows[0]["provider"], "basis": "human ratings" if rows[0]["human_overall"] is not None else "no ratings yet: reliability only"}
    return out
