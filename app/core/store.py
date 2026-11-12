"""Tiny JSON store: gallery, comparison history, ratings, leaderboard."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
import datetime as _dt

CRITERIA = ("prompt_adherence", "visual_quality", "composition",
            "occasion_relevance", "text_safe_area", "logo_safe_area",
            "text_accuracy", "logo_preservation", "color_consistency")


class JsonStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        return {"gallery": [], "comparisons": []}

    def _save(self, db: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(db, fh, indent=1)
        os.replace(tmp, self.path)

    # ---- gallery -------------------------------------------------------
    def add_poster(self, image_path: str, title: str = "", tags=None,
                   meta: dict | None = None) -> dict:
        rec = {"id": uuid.uuid4().hex[:10], "title": title, "tags": tags or [],
               "image_path": image_path, "favorite": False,
               "created": time.time(), "meta": meta or {}}
        with self._lock:
            db = self._load()
            db["gallery"].append(rec)
            self._save(db)
        return rec

    def list_posters(self, q: str = "", favorite: bool | None = None) -> list:
        q = q.lower().strip()
        items = self._load()["gallery"]
        if favorite is not None:
            items = [i for i in items if i["favorite"] == favorite]
        if q:
            items = [i for i in items if q in i["title"].lower()
                     or any(q in t.lower() for t in i["tags"])]
        return sorted(items, key=lambda i: -i["created"])

    def toggle_favorite(self, pid: str) -> dict | None:
        with self._lock:
            db = self._load()
            for i in db["gallery"]:
                if i["id"] == pid:
                    i["favorite"] = not i["favorite"]
                    self._save(db)
                    return i
        return None

    def delete_poster(self, pid: str) -> bool:
        with self._lock:
            db = self._load()
            n = len(db["gallery"])
            db["gallery"] = [i for i in db["gallery"] if i["id"] != pid]
            self._save(db)
            return len(db["gallery"]) < n

    # ---- comparisons / ratings ----------------------------------------
    def add_comparison(self, prompt: str, results: list) -> dict:
        rec = {"id": uuid.uuid4().hex[:10], "prompt": prompt,
               "created": time.time(), "results": results}
        with self._lock:
            db = self._load()
            db["comparisons"].append(rec)
            self._save(db)
        return rec

    def history(self) -> list:
        return sorted(self._load()["comparisons"], key=lambda c: -c["created"])

    def rate(self, cid: str, provider: str, scores: dict) -> bool:
        bad = [k for k in scores if k not in CRITERIA]
        if bad or any(not 1 <= v <= 5 for v in scores.values()):
            raise ValueError(f"scores must use {CRITERIA} with values 1-5")
        with self._lock:
            db = self._load()
            for c in db["comparisons"]:
                if c["id"] == cid:
                    for r in c["results"]:
                        if r["provider"] == provider:
                            r["ratings"] = scores
                            self._save(db)
                            return True
        return False

    def annotate(self, cid: str, provider: str, **fields) -> bool:
        """Attach extra fields (e.g. human notes) to one result row."""
        with self._lock:
            db = self._load()
            for c in db["comparisons"]:
                if c["id"] == cid:
                    for r in c["results"]:
                        if r["provider"] == provider:
                            r.update(fields)
                            self._save(db)
                            return True
        return False

    def leaderboard(self) -> list:
        agg: dict = {}
        for c in self._load()["comparisons"]:
            for r in c["results"]:
                a = agg.setdefault(r["provider"], {"runs": 0, "ok": 0, "ms": [],
                                                   "scores": {k: [] for k in CRITERIA}})
                a["runs"] += 1
                a["ok"] += bool(r["success"])
                if r["success"] and r.get("elapsed_ms") is not None:
                    a["ms"].append(r["elapsed_ms"])
                for k, v in (r.get("ratings") or {}).items():
                    a["scores"][k].append(v)
        rows = []
        for name, a in agg.items():
            avg = {k: round(sum(v) / len(v), 2) for k, v in a["scores"].items() if v}
            rows.append({"provider": name, "runs": a["runs"],
                         "success_rate": round(a["ok"] / a["runs"], 2),
                         "avg_ms": round(sum(a["ms"]) / len(a["ms"]), 1) if a["ms"] else None,
                         "avg_ratings": avg,
                         "overall": round(sum(avg.values()) / len(avg), 2) if avg else None})
        return sorted(rows, key=lambda r: -(r["overall"] or 0))

    # ---- generic collections (projects, brands, campaigns, logs, usage) ----
    def put(self, coll: str, rec: dict) -> dict:
        rec.setdefault("id", uuid.uuid4().hex[:10])
        with self._lock:
            db = self._load()
            items = db.setdefault(coll, [])
            for i, r in enumerate(items):
                if r["id"] == rec["id"]:
                    items[i] = rec
                    break
            else:
                items.append(rec)
            self._save(db)
        return rec

    def get(self, coll: str, rid: str) -> dict | None:
        return next((r for r in self._load().get(coll, []) if r["id"] == rid), None)

    def all(self, coll: str) -> list:
        return self._load().get(coll, [])

    def remove(self, coll: str, rid: str) -> bool:
        with self._lock:
            db = self._load()
            n = len(db.get(coll, []))
            db[coll] = [r for r in db.get(coll, []) if r["id"] != rid]
            self._save(db)
            return len(db[coll]) < n

    def log(self, coll: str, rec: dict, cap: int = 500) -> None:
        rec = {**rec, "time": time.time()}
        with self._lock:
            db = self._load()
            db.setdefault(coll, []).append({"id": uuid.uuid4().hex[:8], **rec})
            db[coll] = db[coll][-cap:]
            self._save(db)

    def incr_usage(self, provider: str) -> None:
        day = _dt.date.today().isoformat()
        with self._lock:
            db = self._load()
            u = db.setdefault("usage", {}).setdefault(day, {})
            u[provider] = u.get(provider, 0) + 1
            self._save(db)

    def usage_today(self) -> dict:
        return self._load().get("usage", {}).get(_dt.date.today().isoformat(), {})
