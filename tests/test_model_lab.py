"""Model Lab: providers (HTTP faked), policy, benchmark, ratings, leaderboard, CSV, selection."""
from __future__ import annotations

import base64
import io
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import guard
from app.core import model_lab as M
from app.core.store import JsonStore


def png(size=(64, 64)):
    b = io.BytesIO()
    Image.new("RGB", size, (200, 80, 40)).save(b, "PNG")
    return b.getvalue()


class Resp:
    def __init__(self, content=b"", js=None, ctype="image/png", status=200):
        self.content, self._js, self.headers, self.status_code = content, js, {"content-type": ctype}, status
        self.text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else str(content)

    def json(self):
        return self._js


class Fake:
    resp, calls = None, []

    def __init__(self, *a, **k): ...
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, **kw):
        Fake.calls.append(("POST", url, kw))
        return Fake.resp

    def get(self, url, **kw):
        Fake.calls.append(("GET", url, kw))
        return Fake.resp


@pytest.fixture()
def fake_http(monkeypatch):
    Fake.calls = []
    monkeypatch.setattr(httpx, "Client", Fake)
    return Fake


def test_providers_build_requests_and_return_png(fake_http, monkeypatch):
    from providers.cloudflare_provider import CloudflareProvider
    from providers.huggingface_provider import HuggingFaceProvider
    from providers.pollinations_provider import PollinationsProvider
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    fake_http.resp = Resp(js={"result": {"image": base64.b64encode(png()).decode()}}, ctype="application/json")
    cf = CloudflareProvider(api_key="t")
    assert cf.generate_image("hello")[:4] == b"\x89PNG"
    assert "/accounts/acct/ai/run/@cf/black-forest-labs/flux-1-schnell" in fake_http.calls[0][1]
    assert fake_http.calls[0][2]["json"] == {"prompt": "hello", "steps": 4}
    fake_http.resp = Resp(png())
    assert HuggingFaceProvider(api_key="k").generate_image("x", width=512, height=512)[:4] == b"\x89PNG"
    assert fake_http.calls[-1][2]["json"]["parameters"] == {"width": 512, "height": 512}
    assert PollinationsProvider().generate_image("a b")[:4] == b"\x89PNG"
    assert "a%20b" in fake_http.calls[-1][1]
    fake_http.resp = Resp(b"<html>nope</html>", ctype="text/html")
    with pytest.raises(RuntimeError, match="did not return an image"):
        PollinationsProvider().generate_image("x")
    fake_http.resp = Resp(b"quota", status=429)
    with pytest.raises(RuntimeError, match="429"):
        HuggingFaceProvider(api_key="k").generate_image("x")
    with pytest.raises(RuntimeError, match="CLOUDFLARE"):
        CloudflareProvider(api_key="").generate_image("x")


def test_policy_and_leaderboard_math():
    assert M.billing_gate({"billing": "free"}, "a", set(), 0)[0]
    assert not M.billing_gate({"billing": "credit", "cost_per_image": .04}, "a", set(), 5)[0]
    assert not M.billing_gate({"billing": "credit", "cost_per_image": .04}, "a", {"a"}, 0)[0]
    assert not M.billing_gate({"billing": "credit"}, "a", {"a"}, 5)[0]
    assert M.billing_gate({"billing": "credit", "cost_per_image": .04}, "a", {"a"}, 5)[0]
    assert not M.spend_ok({"billing": "credit", "cost_per_image": .04}, .98, 1)
    assert M.is_quota_error("HTTP 429: slow down") and not M.is_quota_error("HTTP 500")
    hist = [{"id": "c", "results": [
        {"provider": "a", "success": True, "elapsed_ms": 1000, "est_cost": .1, "category": "festival", "ratings": {"visual_quality": 5}},
        {"provider": "b", "success": True, "elapsed_ms": 500, "est_cost": None, "category": "festival", "ratings": {"visual_quality": 3}},
        {"provider": "b", "success": False, "elapsed_ms": None, "category": "festival"}]}]
    assert [r["provider"] for r in M.leaderboard(hist)["rows"]] == ["a", "b"]
    assert [r["provider"] for r in M.leaderboard(hist, rank_by="speed")["rows"]] == ["b", "a"]
    assert M.leaderboard(hist, rank_by="reliability")["rows"][0]["provider"] == "a"
    assert M.winners(hist)["festival"]["provider"] == "a"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.api as api
    monkeypatch.setattr(api, "store", JsonStore(str(tmp_path / "db.json")))
    monkeypatch.setattr(api.registry, "output_dir", str(tmp_path / "out"))
    os.makedirs(tmp_path / "out")
    guard._inflight.clear()
    return TestClient(api.app)


def test_lab_flow(client, monkeypatch):
    import app.api as api
    ps = {p["name"]: p for p in client.get("/model-lab/providers").json()}
    assert {"mock", "flux", "cloudflare_flux_schnell", "huggingface_flux_schnell", "pollinations_flux"} <= set(ps)
    assert ps["flux"]["billing"] == "credit" and ps["cloudflare_flux_schnell"]["configured"] is False
    d = client.get("/model-lab/dataset").json()
    assert len(d["prompts"]) >= 10 and "text_accuracy" in d["criteria"]
    assert client.get("/model-lab").status_code == 200
    # paid provider blocked without approval and budget
    r = client.post("/model-lab/benchmark", json={"providers": ["flux"], "categories": ["festival"]})
    assert r.status_code == 400 and "flux" in r.json()["detail"]["blocked"]
    # free provider runs; a daily limit stops it
    monkeypatch.setitem(api.registry.config["providers"]["mock"], "daily_limit", 2)
    r = client.post("/model-lab/benchmark", json={"providers": ["mock", "flux"], "categories": ["festival"], "wait": True}).json()
    assert "flux" in r["blocked"] and r["planned_calls"] == 3
    job = client.get(f"/jobs/{r['job_id']}").json()
    assert job["status"] == "done"
    skipped = [x for x in job["results"] if x["status"] == "skipped"]
    assert len(skipped) == 1 and "daily_limit" in skipped[0]["reason"]
    rows = client.get("/model-lab/results", params={"run_id": r["run_id"]}).json()
    assert len(rows) == 2 and rows[0]["estimates"]["kind"] == "automated_estimate" and rows[0]["category"] == "festival"
    img = client.get("/model-lab/image", params={"path": rows[0]["image_path"]})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get("/model-lab/image", params={"path": "/etc/passwd"}).status_code == 404
    # image-needed prompts are skipped without an image, and unsupported features are skipped too
    r2 = client.post("/model-lab/benchmark", json={"providers": ["cloudflare_flux_schnell", "mock"], "prompt_ids": ["logo_preservation"], "wait": True}).json()
    reasons = {x["provider"]: x["reason"] for x in client.get(f"/jobs/{r2['job_id']}").json()["results"]}
    assert "unsupported" in reasons["cloudflare_flux_schnell"] and "image" in reasons["mock"]
    # human rating + notes + leaderboard + csv
    x = rows[0]
    assert client.post("/model-lab/rate", json={"comparison_id": x["comparison_id"], "provider": "mock",
                                                "scores": {"text_accuracy": 4, "visual_quality": 5}, "notes": "good"}).status_code == 200
    assert client.post("/model-lab/rate", json={"comparison_id": x["comparison_id"], "provider": "mock", "scores": {"bogus": 9}}).status_code == 400
    lb = client.get("/model-lab/leaderboard", params={"rank_by": "text_accuracy"}).json()
    assert lb["rows"][0]["provider"] == "mock" and lb["rows"][0]["human_overall"] == 4.5 and "festival" in lb["winners_by_category"]
    assert client.get("/model-lab/leaderboard", params={"rank_by": "nope"}).status_code == 400
    csv_text = client.get("/model-lab/report").text
    assert csv_text.splitlines()[0].startswith("run_id,") and "good" in csv_text and "human_text_accuracy" in csv_text
    # winner selection persists and applies to the existing workflow
    assert client.post("/model-lab/select-winner", json={"feature": "generate_image", "provider": "cloudflare_flux_schnell"}).status_code == 200
    assert client.post("/model-lab/select-winner", json={"feature": "edit_image", "provider": "pollinations_flux"}).status_code == 400
    assert client.post("/model-lab/select-winner", json={"feature": "generate_image", "provider": "mock"}).status_code == 200
    assert client.get("/model-lab/selection").json()["features"]["generate_image"] == "mock"
    assert os.path.exists(os.path.join(api.registry.output_dir, "model_selection.json"))
    monkeypatch.setitem(api.registry.config["providers"]["mock"], "daily_limit", None)
    assert client.post("/model-lab/test-connection", json={"provider": "mock", "live": True}).json()["live"]["success"] is True
    live = client.post("/model-lab/test-connection", json={"provider": "flux", "live": True}).json()["live"]
    assert "approve" in live["skipped"].lower()
