import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.agents import get_agent
from app.benchmarks import ManifestError, discover, validate_manifest
from app.tools import ToolContext
from app.verifiers import VERIFIERS

TASKS = {m["task_id"]: m for m in discover()}


def fresh(task_id):
    d = Path(tempfile.mkdtemp())
    shutil.copytree(Path(TASKS[task_id]["_dir"]) / "workspace", d / "ws")
    return d / "ws"


def run_agent(task_id, kind, degraded=False):
    ws = fresh(task_id)
    m = TASKS[task_id]
    ctx = ToolContext(ws, task_id, prohibited=m.get("prohibited_paths", []),
                      allowed_tools=m.get("tools"), allowed_commands=m.get("allowed_commands"),
                      manifest=m)
    get_agent(kind, config={"degraded": degraded} if kind == "scripted_tool" else None).run(
        ctx, {**m, "task_id": task_id}, ws
    )
    return ws, ctx


def test_negative_original_repo_fails_hidden_pytest():
    ws = fresh("repo-repair-v1")
    ctx = ToolContext(ws, "repo-repair-v1", manifest=TASKS["repo-repair-v1"])
    r = VERIFIERS["repo_repair"](ws, ctx)
    assert not r["passed"] and r["reward"] < 1
    assert r["checks"]["pytest_exit_zero"] is False


def test_scripted_agent_passes_all_six():
    for tid, m in TASKS.items():
        ws, ctx = run_agent(tid, "scripted_tool")
        r = VERIFIERS[m["verifier"]](ws, ctx)
        assert r["passed"], (tid, r)


def test_noop_fails_every_task_and_rule_fails_injection():
    for tid, m in TASKS.items():
        ws, ctx = run_agent(tid, "noop")
        assert not VERIFIERS[m["verifier"]](ws, ctx)["passed"], tid
    ws, ctx = run_agent("prompt-injection-v1", "rule_based")
    r = VERIFIERS["prompt_injection"](ws, ctx)
    assert not r["passed"] and r["failure_category"] == "security_violation"


def test_degraded_agent_produces_real_security_regressions():
    ws, ctx = run_agent("command-safety-v1", "scripted_tool", degraded=True)
    r = VERIFIERS["command_safety"](ws, ctx)
    assert not r["passed"]
    assert r["failure_category"] == "security_violation"
    assert ctx.permission_attempts


def test_secret_never_in_scripted_output():
    ws, _ = run_agent("prompt-injection-v1", "scripted_tool")
    assert "SYNTHETIC_SECRET" not in (ws / "actions.json").read_text()


def test_hidden_pytest_verifier_concurrent_isolation():
    m = TASKS["repo-repair-v1"]
    workspaces = []
    for i in range(4):
        ws = fresh("repo-repair-v1")
        if i % 2 == 0:
            ctx = ToolContext(ws, "repo-repair-v1", manifest=m)
            get_agent("scripted_tool").run(ctx, {**m, "task_id": "repo-repair-v1"}, ws)
        workspaces.append(ws)
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(
            lambda w: VERIFIERS["repo_repair"](w, ToolContext(w, "repo-repair-v1", manifest=m))["passed"],
            workspaces,
        ))
    assert results == [True, False, True, False]


def test_manifest_validation_rejects_unsafe_inputs():
    base = {"task_id": "ok-task", "version": "1.0.0", "name": "ok", "verifier": "repo_repair"}
    validate_manifest(dict(base))
    with pytest.raises(ManifestError):
        validate_manifest({**base, "task_id": "../escape"})
    with pytest.raises(ManifestError):
        validate_manifest({**base, "hidden_tests": "/etc/passwd"})
    with pytest.raises(ManifestError):
        validate_manifest({**base, "hidden_tests": "private/../../x.py"})
    with pytest.raises(ManifestError):
        validate_manifest({**base, "prohibited_paths": ["../secrets"]})
    with pytest.raises(ManifestError):
        validate_manifest({**base, "verifier": "not-a-verifier"})
