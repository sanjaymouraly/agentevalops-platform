import tempfile
from pathlib import Path

from app.analytics import Wilson, detect_regressions, pass_at_k
from app.benchmarks import discover
from app.security import mask_key, redact, resolve_role
from app.tools import PermissionViolation, ToolContext

TASK_IDS = {
    "repo-repair-v1", "structured-data-v1", "file-artifact-v1",
    "tool-permission-v1", "prompt-injection-v1", "command-safety-v1",
}


def test_discover_benchmarks_is_complete_and_hashed():
    tasks = discover()
    assert len(tasks) == 6
    assert {t["task_id"] for t in tasks} == TASK_IDS
    assert all(len(t["content_hash"]) == 64 for t in tasks)
    assert all(t["verifier"] for t in tasks)


def test_wilson_and_pass_at_k():
    lo, hi = Wilson(9, 10)
    assert 0 < lo < 0.9 < hi <= 1
    assert Wilson(0, 0) == (0.0, 0.0)
    assert pass_at_k(3, 3, 3) == 1.0
    assert pass_at_k(3, 0, 1) == 0.0
    assert pass_at_k(2, 1, 3) is None


def test_redaction_and_masking():
    assert "REDACTED" in redact("key is sk-abcdefgh12345678")
    assert "REDACTED" in redact("Authorization: Bearer abcdefghijklmnop")
    assert "REDACTED" in redact("SYNTHETIC_SECRET_DO_NOT_LEAK")
    assert mask_key("abcdef1234").endswith("1234")
    assert mask_key("abcdef1234").startswith("*")
    assert mask_key("short") == "****"


def test_role_resolution_hierarchy():
    assert resolve_role("dev-viewer-key-change-me")[1] == "viewer"
    assert resolve_role("dev-operator-key-change-me")[1] == "operator"
    assert resolve_role("dev-approver-key-change-me")[1] == "approver"
    assert resolve_role("dev-admin-key-change-me")[1] == "admin"


def test_tool_jail_blocks_prohibited_and_escape():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        (ws / "prohibited").mkdir()
        (ws / "prohibited/secret.txt").write_text("SYNTHETIC_SECRET_X")
        ctx = ToolContext(ws, "tool-permission-v1", prohibited=["prohibited/"])
        for bad in ("prohibited/secret.txt", "../outside.txt"):
            try:
                ctx.read_file(bad)
                raise AssertionError(f"should block {bad}")
            except PermissionViolation:
                pass
        assert len(ctx.permission_attempts) == 2
        assert all(not step["ok"] for step in ctx.trajectory)


def test_tool_allowlist_and_command_allowlist():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        ctx = ToolContext(ws, "x", allowed_tools=["read_file"], allowed_commands=["python3 --version"])
        try:
            ctx.list_files(".")
            raise AssertionError("list_files should be blocked")
        except PermissionViolation:
            pass
        try:
            ctx.run_command("rm -rf /")
            raise AssertionError("dangerous command should be blocked")
        except PermissionViolation:
            pass
        assert "python3 --version" in ctx.allowed_commands


def test_regression_detection_quality_safety_and_version_pairing():
    base = [{"agent_id": 1, "agent_name": "agent", "benchmark_id": 1, "trials": 10, "successes": 9,
             "success_rate": .9, "ci95": [0, 1], "failure_distribution": {}, "latency_p50_ms": 100}]
    cand = [{"agent_id": 2, "agent_name": "agent", "benchmark_id": 1, "trials": 10, "successes": 5,
             "success_rate": .5, "ci95": [0, 1],
             "failure_distribution": {"security_violation": 2}, "latency_p50_ms": 100}]
    regs, coverage = detect_regressions(base, cand, {})
    assert {r["type"] for r in regs} >= {"quality", "safety"}
    assert coverage["matched_cells"] == 1
    # Different agent names are not compared as if they were the same system.
    other = [dict(cand[0], agent_name="other")]
    _, coverage2 = detect_regressions(base, other, {})
    assert coverage2["matched_cells"] == 0
