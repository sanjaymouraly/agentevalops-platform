import json
import tempfile
from pathlib import Path

from app.benchmarks import discover, load_manifest
from app.classification import classify
from app.harbor_adapter import export_harbor_task, import_harbor_task, parse_harbor_reward
from app.pdf import text_to_pdf
from app.providers import MockProvider, OpenAICompatibleProvider
from app.sandbox import POLICY, build_docker_command


def test_docker_command_is_restricted():
    cmd = build_docker_command("python:3.12-slim", "/tmp/trial-ws", 7)
    joined = " ".join(cmd)
    assert "--network none" in joined and "--cap-drop ALL" in joined and "--read-only" in joined
    assert "--privileged" not in joined and "docker.sock" not in joined
    assert POLICY["docker"]["privileged"] is False


def test_pdf_is_valid():
    with tempfile.TemporaryDirectory() as d:
        out = text_to_pdf("Test Report", "Gate: PASS\n" + "line of evidence\n" * 80, Path(d) / "r.pdf")
        data = Path(out).read_bytes()
        assert data.startswith(b"%PDF-1.4") and b"%%EOF" in data and len(data) > 800


def test_mock_provider_is_labelled_and_never_claimed_as_llm():
    r = MockProvider().chat([{"role": "user", "content": "hello"}])
    assert r["input_tokens"] >= 1 and r["estimated_cost_usd"] == 0.0
    assert "mock" in r["cost_provenance"]
    assert MockProvider().test_connection()["ok"] is True


def test_openai_compatible_provider_without_server_fails_cleanly():
    p = OpenAICompatibleProvider("http://127.0.0.1:9/v1", model="m")
    res = p.test_connection()
    assert res["ok"] is False and res["error_kind"] in ("provider_failure", "auth_error")


def test_openai_compatible_cost_is_unknown_without_pricing():
    from app import providers as prov
    original = prov.httpx.post

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "hi"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    prov.httpx.post = lambda *a, **k: FakeResp()
    try:
        p = OpenAICompatibleProvider("http://local/v1", api_key="test-key", model="m")
        r = p.chat([{"role": "user", "content": "x"}])
        assert r["text"] == "hi" and r["input_tokens"] == 10
        assert r["estimated_cost_usd"] is None
        assert "pricing not configured" in r["cost_provenance"]
    finally:
        prov.httpx.post = original


def test_llm_agent_never_fakes_inference():
    from app.agents import LLMAgent
    from app.tools import ToolContext

    with tempfile.TemporaryDirectory() as d:
        ctx = ToolContext(Path(d), "repo-repair-v1")
        try:
            LLMAgent(provider=None).run(ctx, {"task_id": "x", "instruction": "y"}, Path(d))
            raise AssertionError("must fail without a provider")
        except RuntimeError as e:
            assert "provider_not_configured" in str(e)


def test_classification_rules_are_evidence_based():
    assert classify("timed_out", None, None)[0] == "timeout"
    assert classify("failed", None, None, RuntimeError("provider API down"))[0] == "provider_failure"
    assert classify("failed", None, None)[0] == "infrastructure_failure"
    assert classify("completed", {"passed": True, "checks": {}}, None)[0] == "none"
    assert classify("completed", {"passed": False, "failure_category": "security_violation"},
                    None)[0] == "security_violation"


def test_harbor_export_contains_real_verifier_and_round_trips():
    tasks = {m["task_id"]: m for m in discover()}
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        dest = export_harbor_task(tasks["repo-repair-v1"], Path(tasks["repo-repair-v1"]["_dir"]), root / "harbor")
        assert (dest / "task.toml").exists()
        shell = (dest / "tests" / "test.sh").read_text()
        assert "verifier/run.py" in shell and "reward.txt" in shell
        assert "Replace with" not in shell
        assert (dest / "tests" / "verifier" / "verifiers.py").exists()
        assert (dest / "tests" / "private" / "test_calc.py").exists()
        assert "workspace/" in (dest / "environment" / "Dockerfile").read_text()

        imported = import_harbor_task(dest, root / "examples")
        assert imported["task_id"] == "repo-repair-v1"
        reloaded = load_manifest(root / "examples" / "repo-repair-v1")
        assert reloaded["hidden_tests"] == "private/test_calc.py"

        trial = root / "trial"
        (trial / "logs" / "verifier").mkdir(parents=True)
        (trial / "logs" / "verifier" / "reward.txt").write_text("1.0\n")
        (trial / "logs" / "verifier" / "reward.json").write_text(json.dumps({"reward": 0.5}))
        assert parse_harbor_reward(trial)["reward"] == 1.0
