"""Child-process trial worker: runs exactly one agent.

Invoked as ``python -m app.trial_worker <input.json> <output.json>`` by the
execution engine (local subprocess mode and Docker mode). Keeping the agent in
a separate process makes hard timeouts, process-group kill and resource limits
possible. Only the provider API key named by ``api_key_env`` is forwarded.
"""
import json
import sys
from pathlib import Path

try:  # POSIX only; Windows has no resource module.
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None


def _apply_limits(timeout_sec: int, max_file_bytes: int):
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout_sec) + 10, int(timeout_sec) + 20))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (int(max_file_bytes), int(max_file_bytes)))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
    except Exception:
        pass


def main():
    inp = json.loads(Path(sys.argv[1]).read_text())
    out_path = Path(sys.argv[2])
    _apply_limits(inp.get("timeout_sec", 120), inp.get("max_file_bytes", 1_000_000))
    from .agents import get_agent
    from .providers import build_provider
    from .tools import ToolContext

    ws = Path(inp["workspace"])
    manifest = inp.get("manifest") or {}
    ctx = ToolContext(
        ws, inp["task_id"], prohibited=inp.get("prohibited_paths", []),
        allowed_tools=inp.get("allowed_tools"), allowed_commands=inp.get("allowed_commands"),
        max_file_bytes=int(inp.get("max_file_bytes", 1_000_000)), manifest=manifest,
    )
    task = {
        "task_id": inp["task_id"], "instruction": inp.get("instruction", ""),
        "prohibited_paths": inp.get("prohibited_paths", []),
        "tools": inp.get("allowed_tools") or [],
        "allowed_commands": inp.get("allowed_commands") or [],
        "manifest": manifest,
    }
    provider = None
    if inp["agent_kind"] == "llm":
        pcfg = inp.get("provider_cfg", {})
        provider = build_provider(
            pcfg.get("provider_type", "mock"), pcfg.get("base_url", ""),
            pcfg.get("model", ""), pcfg.get("api_key_env", ""), pcfg.get("params") or {},
        )
    try:
        result = get_agent(inp["agent_kind"], provider=provider, config=inp.get("agent_config") or {}).run(ctx, task, ws)
        payload = {
            "notes": result.notes, "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens, "estimated_cost_usd": result.estimated_cost_usd,
            "cost_provenance": result.cost_provenance, "status": result.status,
            "error_kind": result.error_kind, "trajectory": ctx.trajectory,
            "permission_attempts": ctx.permission_attempts, "error": "",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        payload = {
            "notes": "", "input_tokens": None, "output_tokens": None, "estimated_cost_usd": None,
            "cost_provenance": "unknown", "status": "failed", "error_kind": type(e).__name__,
            "trajectory": ctx.trajectory, "permission_attempts": ctx.permission_attempts,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-1500:],
        }
    out_path.write_text(json.dumps(payload, default=str))


if __name__ == "__main__":
    main()
