import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from app.agents import CALC_FIXED, LLMAgent
from app.benchmarks import discover
from app.providers import build_provider
from app.tools import PermissionViolation, ToolContext
from app.verifiers import VERIFIERS

CALLS = {"n": 0}


class FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-1"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        CALLS["n"] += 1
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if CALLS["n"] == 1:
            text = json.dumps({"actions": [{"tool": "write_file", "path": "calc.py", "content": CALC_FIXED}],
                               "done": False})
        else:
            text = json.dumps({"actions": [], "done": True})
        body = json.dumps({
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 17},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def test_llm_loop_against_local_openai_compatible_server(monkeypatch):
    monkeypatch.setenv("CUSTOM_OPENAI_API_KEY", "test-key")
    CALLS["n"] = 0
    server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        provider = build_provider("custom_openai", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                  model="fake-1", params={"input_price_per_million": 1.0,
                                                          "output_price_per_million": 2.0})
        assert provider.test_connection()["ok"] is True
        tasks = {m["task_id"]: m for m in discover()}
        m = tasks["repo-repair-v1"]
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "ws"
            shutil.copytree(Path(m["_dir"]) / "workspace", ws)
            ctx = ToolContext(ws, "repo-repair-v1", prohibited=m.get("prohibited_paths", []), manifest=m)
            result = LLMAgent(provider=provider).run(ctx, {**m, "task_id": "repo-repair-v1"}, ws)
            assert result.input_tokens == 84 and result.output_tokens == 34
            assert result.estimated_cost_usd > 0
            verifier = VERIFIERS["repo_repair"](ws, ctx)
            assert verifier["passed"], verifier
            assert any(step["tool"] == "provider_chat" for step in ctx.trajectory)
    finally:
        server.shutdown()


def test_command_tool_allowlist_blocks_dangerous():
    with tempfile.TemporaryDirectory() as d:
        ctx = ToolContext(Path(d), "command-safety-v1")
        out = ctx.run_command("python3 --version")
        assert out.startswith("Python 3.")
        for bad in ("rm -rf /", "curl https://x", "cat /etc/passwd", "python3 -c 'print(1)'"):
            try:
                ctx.run_command(bad)
                raise AssertionError(bad)
            except PermissionViolation:
                pass
        assert len(ctx.permission_attempts) == 4
