"""Execution sandbox policies and Docker runner.

Local subprocess mode uses a fresh workspace, sanitized environment, hard
timeout, process-group kill and POSIX resource limits. Docker mode adds
namespace/container isolation. Docker is still not a hostile multi-tenant
boundary; a microVM/gVisor worker is the documented next step (SECURITY.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import get_settings

POLICY = {
    "local": {
        "fresh_workspace_per_trial": True, "path_jail": True, "prohibited_prefixes": True,
        "tool_allowlist": True, "timeout_enforced": True, "host_secrets_in_env": False,
        "network": "agents run in-process; tool layer exposes no network tool",
        "limitation": "Not a security boundary for hostile multi-tenant code.",
    },
    "subprocess": {
        "fresh_workspace_per_trial": True, "path_jail": True, "tool_allowlist": True,
        "hard_timeout": True, "process_group_kill": True, "rlimits": ["CPU", "AS", "FSIZE", "NPROC"],
        "host_secrets_in_env": False, "network": "agent code could open sockets; use docker mode for untrusted code",
        "limitation": "OS process isolation only; container/microVM isolation is recommended.",
    },
    "docker": {
        "user": "uid 1000", "cap_drop": ["ALL"], "network": "configurable (default none)",
        "read_only_rootfs": True, "memory_mb": 512, "cpus": 1, "pids_limit": 128,
        "privileged": False, "no_docker_socket": True,
        "limitation": "Docker alone does not make arbitrary hostile code safe for multi-tenant execution.",
    },
    "future_hardened": "microVM (Firecracker/gVisor) worker behind the same executor contract",
}


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


def docker_image_available(image: str | None = None) -> bool:
    image = image or get_settings().docker_image
    if not docker_available():
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True,
                              timeout=8).returncode == 0
    except Exception:
        return False


def build_docker_command(image: str, workspace, trial_id: int, memory_mb: int = 512,
                         cpus: int = 1, artifact_dir=None, backend_dir=None,
                         network: str = "none", user: str = "1000:1000",
                         command: list[str] | None = None,
                         input_file: str = "/artifact/agent_input.json",
                         output_file: str = "/artifact/agent_output.json",
                         api_key_env: str | None = None) -> list[str]:
    """Build a restricted ``docker run`` argv. Never mounts the Docker socket."""
    artifact = Path(artifact_dir) if artifact_dir else Path(workspace).parent
    backend = Path(backend_dir) if backend_dir else Path(__file__).resolve().parents[1]
    cmd = [
        "docker", "run", "--rm", "--name", f"agentevalops-trial-{trial_id}",
        "--network", network, "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128",
        "--memory", f"{memory_mb}m", "--cpus", str(cpus),
        "--read-only", "--tmpfs", "/tmp:size=64m", "--user", user,
        "-v", f"{Path(workspace).resolve()}:/workspace:rw",
        "-v", f"{artifact.resolve()}:/artifact:rw",
        "-v", f"{backend.resolve()}:/app:ro",
        "-w", "/workspace", "-e", "HOME=/tmp", "-e", "PYTHONPATH=/app",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "LANG=C.UTF-8",
    ]
    if api_key_env and os.environ.get(api_key_env):
        cmd += ["-e", f"{api_key_env}={os.environ[api_key_env]}"]
    cmd += [image]
    cmd += command or ["python", "-m", "app.trial_worker", input_file, output_file]
    return cmd


def run_in_docker(workspace: Path, artifact_dir: Path, trial_id: int, timeout: int,
                  memory_mb: int = 512, cpus: float = 1, artifact: Path | None = None,
                  api_key_env: str | None = None) -> dict:
    """Run the trial worker in the restricted container. Returns a structured result."""
    settings = get_settings()
    if not docker_image_available(settings.docker_image):
        return {"infrastructure_error": f"Docker runner image '{settings.docker_image}' not found. Run scripts/build_runner.sh"}
    art = artifact or artifact_dir
    art.mkdir(parents=True, exist_ok=True)
    cmd = build_docker_command(
        settings.docker_image, workspace, trial_id, memory_mb=memory_mb, cpus=cpus,
        artifact_dir=art, backend_dir=Path(__file__).resolve().parents[1],
        network=settings.docker_network, api_key_env=api_key_env,
    )
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout) + 20)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", f"agentevalops-trial-{trial_id}"], capture_output=True)
        return {"timed_out": True, "trajectory": [], "permission_attempts": []}
    except Exception as e:
        return {"infrastructure_error": f"Docker execution failed: {e}"}
    out_path = art / "agent_output.json"
    if proc.returncode != 0 or not out_path.exists():
        return {"infrastructure_error": f"docker exit {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}",
                "docker_stderr": (proc.stderr or "")[-2000:]}
    try:
        data = json.loads(out_path.read_text())
    except Exception as e:
        return {"infrastructure_error": f"invalid container output: {e}"}
    data["latency_ms"] = round((time.time() - started) * 1000, 2)
    data["sandbox"] = "docker"
    return data
