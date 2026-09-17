"""Opt-in live Ollama smoke test (no paid API calls).

Run with ``AGENTEVALOPS_TEST_OLLAMA=1`` when a local Ollama daemon has a model.
The test asserts that a real provider responds and that the trial records real
token usage — it never substitutes mock inference.
"""
import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTEVALOPS_TEST_OLLAMA") != "1",
    reason="set AGENTEVALOPS_TEST_OLLAMA=1 to run against a local Ollama daemon",
)


def test_ollama_provider_chat_is_real():
    from app.providers import build_provider

    provider = build_provider("ollama", "http://localhost:11434/v1", "gemma:2b")
    result = provider.chat([{"role": "user", "content": "Reply with the single word: ready"}])
    assert result["text"].strip()
    assert result["input_tokens"] and result["input_tokens"] > 0
    assert result["estimated_cost_usd"] == 0.0
    assert "local inference" in result["cost_provenance"]


def test_ollama_agent_trial_records_real_usage(client, benchmarks):
    agents = client.get("/api/v1/agents").json()
    llm = next(a for a in agents if a["kind"] == "llm")
    bench = next(b for b in benchmarks if b["task_id"] == "repo-repair-v1")
    e = client.post("/api/v1/experiments", json={
        "name": f"ollama-live-{time.time()}", "agent_ids": [llm["id"]],
        "benchmark_ids": [bench["id"]], "repetitions": 1,
    }).json()
    result = client.post(f"/api/v1/experiments/{e['id']}/run", params={"wait": "true"}).json()
    trial = result["trials"][0]
    assert trial["status"] in ("completed", "failed", "timed_out")
    assert trial["config_snapshot"]["provider"] == "ollama"
    if trial["status"] == "completed":
        assert (trial["input_tokens"] or 0) > 0
        assert trial["cost_provenance"].startswith("local inference")
