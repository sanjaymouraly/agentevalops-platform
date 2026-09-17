import shutil
import tempfile
import time
from pathlib import Path

from app.benchmarks import discover
from app.execution import _run_agent_subprocess
from app.tools import ToolContext
from app.verifiers import VERIFIERS

TASKS = {m["task_id"]: m for m in discover()}


def test_subprocess_scripted_agent_passes_with_trajectory():
    m = TASKS["repo-repair-v1"]
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "ws"
        shutil.copytree(Path(m["_dir"]) / "workspace", ws)
        out = _run_agent_subprocess(m, "repo-repair-v1", "scripted_tool", {}, ws, Path(d) / "art", timeout=60)
        assert not out.get("timed_out") and not out["error"], out
        assert out["trajectory"], "trajectory must survive the process boundary"
        ctx = ToolContext(ws, "repo-repair-v1", manifest=m)
        ctx.trajectory = out["trajectory"]
        assert VERIFIERS["repo_repair"](ws, ctx)["passed"]


def test_subprocess_hard_timeout_kills_sleeper():
    m = TASKS["repo-repair-v1"]
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "ws"
        shutil.copytree(Path(m["_dir"]) / "workspace", ws)
        started = time.time()
        out = _run_agent_subprocess(m, "repo-repair-v1", "sleeper", {}, ws, Path(d) / "art", timeout=2)
        elapsed = time.time() - started
        assert out["timed_out"] is True
        assert elapsed < 20, f"sleeper was not hard-killed (elapsed {elapsed:.1f}s)"


def test_full_trial_in_subprocess_mode(client, scripted_agent, benchmarks):
    sec = next(b for b in benchmarks if b["task_id"] == "prompt-injection-v1")
    e = client.post("/api/v1/experiments", json={
        "name": "subprocess mode e2e", "agent_ids": [scripted_agent["id"]],
        "benchmark_ids": [sec["id"]], "repetitions": 1,
    }).json()
    r = client.post(f"/api/v1/experiments/{e['id']}/run").json()
    assert r["summary"]["overall"]["trials"] == 1
    assert r["summary"]["overall"]["successes"] == 1, r["summary"]
    trial = r["trials"][0]
    assert trial["config_snapshot"]["execution_mode"] == "subprocess"
    detail = client.get(f"/api/v1/trials/{trial['id']}").json()
    assert detail["trajectory"]["steps"], "trajectory must cross the process boundary intact"
    events = {e["event"] for e in detail["events"]}
    assert {"preparing", "running", "verifying", "finished"} <= events
