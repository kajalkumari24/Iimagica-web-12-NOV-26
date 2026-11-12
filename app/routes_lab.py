"""Model Lab API under /model-lab: providers, dataset benchmark, human ratings, leaderboard, CSV, winner selection."""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import uuid

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response

from .core import model_lab as M
from .core.base import FEATURES
from .core.jobs import call
from .core.store import CRITERIA
from .routes_studio import jobs


def build_lab_router(ctx) -> APIRouter:
    r = APIRouter(prefix="/model-lab", tags=["model-lab"])
    reg, st = (lambda: ctx.registry), (lambda: ctx.store)
    cfg = lambda n: ((reg().config.get("providers") or {}).get(n) or {})  # noqa: E731
    sel_path = lambda: os.path.join(reg().output_dir, "model_selection.json")  # noqa: E731

    def need(d, *keys):
        miss = [k for k in keys if k not in d]
        if miss:
            raise HTTPException(400, f"Missing: {miss}")

    def known(names):
        bad = [n for n in names if n not in reg().providers]
        if bad or not names:
            raise HTTPException(400, f"Give known providers (unknown: {bad})")

    try:  # re-apply the saved production selection on startup
        with open(sel_path(), encoding="utf-8") as fh:
            for f, p in json.load(fh).get("features", {}).items():
                reg().set_feature_provider(f, p)
    except Exception:  # noqa: BLE001
        pass

    def info(name):
        p, spec = reg().providers[name], cfg(name)
        used, lim = st().usage_today().get(name, 0), spec.get("daily_limit")
        conf = getattr(p, "configured", None)
        rem_credits = getattr(p, "get_remaining_credits", lambda: None)()
        status = spec.get("status") or ("FREE" if spec.get("billing") in ("free", "free_tier") else ("TRIAL" if spec.get("billing") == "trial" else "PAID"))
        return {"name": name, "display_name": spec.get("display_name", p.display_name), "model_id": p.model_id,
                "capabilities": sorted(p.capabilities), "supports_editing": "edit_image" in p.capabilities,
                "configured": bool(getattr(p, "api_key", True)) if conf is None else bool(conf),
                "billing": spec.get("billing", "unknown"), "status": status,
                "free_tier_note": spec.get("free_tier_note"),
                "credits_remaining": rem_credits,
                "cost_per_image": spec.get("cost_per_image"),
                "quota": {"used_today": used, "daily_limit": lim, "remaining": None if lim is None else max(0, lim - used), "credits": rem_credits}}

    @r.get("")
    def page():
        return FileResponse(os.path.join(os.path.dirname(__file__), "static", "model_lab.html"))

    @r.get("/providers")
    def providers():
        return [info(n) for n in reg().providers]

    models = providers  # one model per provider entry in this project
    r.get("/models")(models)

    @r.post("/test-connection")
    def test_connection(body: dict = Body(...)):
        """Cheap config check; live=true makes ONE tiny generation, subject to the same billing and quota rules."""
        need(body, "provider")
        n = body["provider"]
        known([n])
        out = {"provider": n, "health": reg().providers[n].health_check()}
        if body.get("live"):
            ok, why = M.billing_gate(cfg(n), n, set(body.get("approve_paid", [])), float(body.get("budget", 0)))
            lim, used = cfg(n).get("daily_limit"), st().usage_today().get(n, 0)
            if not ok:
                out["live"] = {"skipped": why}
            elif lim is not None and used >= lim:
                out["live"] = {"skipped": "daily_limit reached"}
            else:
                o = call(reg(), st(), n, "generate_image", retries=0, prompt="a plain red circle on a white background", width=512, height=512)
                out["live"] = {"success": o["success"], "error": o["error"], "elapsed_ms": o["elapsed_ms"]}
        return out

    @r.get("/dataset")
    def dataset():
        return {"prompts": M.load_dataset(), "criteria": CRITERIA}

    @r.post("/benchmark")
    def benchmark(body: dict = Body(...)):
        """Runs the fixed dataset. Paid providers need approve_paid AND budget; quota/rate errors stop that provider."""
        need(body, "providers")
        names = list(body["providers"])
        known(names)
        entries = M.select_entries(body.get("prompt_ids"), body.get("categories"))
        if not entries:
            raise HTTPException(400, "No dataset prompts match")
        img = base64.b64decode(body["image_base64"]) if body.get("image_base64") else None
        reps, w, h = max(1, min(5, int(body.get("repeats", 1)))), int(body.get("width", 1024)), int(body.get("height", 1024))
        approve, budget = set(body.get("approve_paid", [])), float(body.get("budget", 0))
        blocked, run = {}, []
        for n in names:
            ok, why = M.billing_gate(cfg(n), n, approve, budget)
            (run.append(n) if ok else blocked.__setitem__(n, why))
        if not run:
            raise HTTPException(400, {"message": "No provider may run", "blocked": blocked})
        run_id, state, stopped = uuid.uuid4().hex[:8], {"spent": 0.0}, {}

        def work():
            for e in entries:
                for rep in range(reps):
                    rows = []
                    for n in run:
                        spec, prov = cfg(n), reg().providers[n]
                        row = {"provider": n, "prompt_id": e["id"], "category": e["category"], "feature": e["feature"],
                               "repeat": rep, "run_id": run_id, "billing": spec.get("billing", "unknown"),
                               "tier_status": spec.get("status") or ("FREE" if spec.get("billing") in ("free", "free_tier") else ("TRIAL" if spec.get("billing") == "trial" else "PAID"))}
                        lim, used = spec.get("daily_limit"), st().usage_today().get(n, 0)
                        skip = (stopped.get(n) or ("unsupported feature" if e["feature"] not in prov.capabilities else None)
                                or ("needs image_base64" if e["needs_image"] and img is None else None)
                                or ("daily_limit reached" if lim is not None and used >= lim else None)
                                or (None if M.spend_ok(spec, state["spent"], budget) else "budget would be exceeded"))
                        if skip:
                            yield {**row, "status": "skipped", "reason": skip}
                            continue
                        kw = {"prompt": e["prompt"]}
                        kw.update({"width": w, "height": h} if e["feature"] == "generate_image" else {"image_bytes": img})
                        o = call(reg(), st(), n, e["feature"], retries=0, **kw)
                        row.update(success=o["success"], error=o["error"], elapsed_ms=o["elapsed_ms"], est_cost=o["est_cost"],
                                   model_id=o["model_id"], attempts=o["attempts"], image_path=None, status="ok" if o["success"] else "failed")
                        if o["success"]:
                            state["spent"] += float(spec.get("cost_per_image") or 0) if row["billing"] not in M.FREE else 0
                            if isinstance(o["data"], bytes):
                                row["image_path"] = ctx._save_output(f"benchmark/{n}", o["data"])
                                row["estimates"] = M.auto_estimates(o["data"], w, h, e["expected_text"])
                        elif M.is_quota_error(o["error"]):
                            stopped[n] = "quota or rate limit reached; stopped for this run"
                        rows.append(row)
                        yield row
                    if rows:
                        st().add_comparison(f"[dataset:{run_id}] {e['id']}", rows)

        total = len(entries) * reps * len(run)
        return {"job_id": jobs.start(total, work, bool(body.get("wait"))), "run_id": run_id, "planned_calls": total, "blocked": blocked}

    @r.get("/results")
    def results(run_id: str | None = None, category: str | None = None, provider: str | None = None, limit: int = 500):
        out = []
        for c in st().history():
            for x in c["results"]:
                if (run_id and x.get("run_id") != run_id) or (category and x.get("category") != category) \
                        or (provider and x.get("provider") != provider):
                    continue
                out.append({**x, "comparison_id": c["id"], "prompt": c["prompt"]})
        return out[:max(1, min(limit, 2000))]

    @r.get("/image")
    def image(path: str):
        root, real = os.path.realpath(reg().output_dir), os.path.realpath(path)
        if not real.startswith(root + os.sep) or not os.path.isfile(real):
            raise HTTPException(404, "Image not found")
        return FileResponse(real)

    @r.post("/rate")
    def rate(body: dict = Body(...)):
        """Human ratings (1-5) and notes. These are separate from automated estimates."""
        need(body, "comparison_id", "provider", "scores")
        try:
            ok = st().rate(body["comparison_id"], body["provider"], body["scores"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not ok:
            raise HTTPException(404, "Result not found")
        if body.get("notes"):
            st().annotate(body["comparison_id"], body["provider"], notes=str(body["notes"])[:1000])
        return {"ok": True}

    @r.get("/leaderboard")
    def board(category: str | None = None, rank_by: str = "overall"):
        if rank_by not in M.RANKS:
            raise HTTPException(400, f"rank_by must be one of {list(M.RANKS)}")
        out = M.leaderboard(st().history(), category, rank_by)
        out["winners_by_category"] = M.winners(st().history())
        return out

    @r.get("/report")
    def report(format: str = "csv", run_id: str | None = None):
        rows = results(run_id=run_id, limit=2000)
        if format == "json":
            return rows
        buf, w = io.StringIO(), None
        w = csv.writer(buf)
        head = ["run_id", "comparison_id", "prompt_id", "category", "provider", "model_id", "feature", "repeat", "success",
                "error", "elapsed_ms", "est_cost", "billing", "aspect_ok", "heuristic_design_score", "text_similarity"]
        w.writerow(head + [f"human_{c}" for c in CRITERIA] + ["notes", "image_path"])
        for x in rows:
            e, hr = x.get("estimates") or {}, x.get("ratings") or {}
            w.writerow([x.get("run_id"), x["comparison_id"], x.get("prompt_id"), x.get("category"), x["provider"], x.get("model_id"),
                        x.get("feature"), x.get("repeat"), x.get("success"), x.get("error"), x.get("elapsed_ms"), x.get("est_cost"),
                        x.get("billing"), e.get("aspect_ok"), e.get("heuristic_design_score"), e.get("text_similarity")]
                       + [hr.get(c) for c in CRITERIA] + [x.get("notes"), x.get("image_path")])
        return Response(buf.getvalue(), media_type="text/csv")

    @r.post("/select-winner")
    def select_winner(body: dict = Body(...)):
        """Point a production feature at a tested provider. Persists across restarts; no code change needed."""
        need(body, "feature", "provider")
        f, n = body["feature"], body["provider"]
        known([n])
        if f not in FEATURES:
            raise HTTPException(400, f"feature must be one of {list(FEATURES)}")
        if f not in reg().providers[n].capabilities:
            raise HTTPException(400, f"{n} does not support {f}")
        reg().set_feature_provider(f, n)
        try:
            with open(sel_path(), encoding="utf-8") as fh:
                saved = json.load(fh)
        except Exception:  # noqa: BLE001
            saved = {}
        saved.setdefault("features", {})[f] = n
        os.makedirs(reg().output_dir, exist_ok=True)
        with open(sel_path(), "w", encoding="utf-8") as fh:
            json.dump(saved, fh, indent=1)
        return {"feature": f, "provider": n, "saved": True}

    @r.get("/selection")
    def selection():
        return {"default_provider": reg().default_provider, "features": reg().features}

    return r
