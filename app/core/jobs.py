"""Provider call with retry/logging/usage/cost, plus background jobs with progress."""
from __future__ import annotations

import threading
import time
import uuid


def call(registry, store, name: str, feature: str, retries: int = 2,
         backoff: float = 0.5, **kw) -> dict:
    """Run provider.<feature>(**kw) with retries. Never raises.

    Returns {success, data, error, attempts, elapsed_ms, est_cost, model_id}.
    Providers return raw data and raise on failure (see registry.run).
    """
    prov = registry.providers[name]
    cost = ((registry.config.get("providers") or {}).get(name) or {}).get("cost_per_image")
    start, out = time.perf_counter(), {"success": False, "data": None, "error": None}
    attempts = 0
    for i in range(retries + 1):
        attempts = i + 1
        try:
            out.update(success=True, data=getattr(prov, feature)(**kw), error=None)
        except Exception as exc:  # noqa: BLE001
            out.update(success=False, error=str(exc))
        store.incr_usage(name)
        if out["success"]:
            break
        store.log("errors", {"provider": name, "feature": feature,
                             "error": out["error"], "attempt": attempts})
        if i < retries:
            time.sleep(backoff * 2 ** i)
    out.update(attempts=attempts, model_id=prov.model_id,
               elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
               est_cost=cost if out["success"] else None)
    return out


class Jobs:
    """In-memory background jobs. worker() is a generator yielding result dicts."""

    recent: dict = {}  # shared, so a refreshed page can list jobs again

    def __init__(self):
        self.jobs: dict = {}

    def start(self, total: int, worker, wait: bool = False) -> str:
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "status": "running", "done": 0, "total": total,
               "results": [], "error": None}
        self.jobs[jid] = job
        Jobs.recent[jid] = job
        for k in list(Jobs.recent)[:-50]:
            Jobs.recent.pop(k)

        def run():
            try:
                for r in worker():
                    job["results"].append(r)
                    job["done"] += 1
                job["status"] = "done"
            except Exception as exc:  # noqa: BLE001
                job["status"], job["error"] = "failed", str(exc)

        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()
        return jid

    def get(self, jid: str) -> dict | None:
        return self.jobs.get(jid)
