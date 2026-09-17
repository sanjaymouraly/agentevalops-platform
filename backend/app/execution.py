"""Trial and experiment execution engine.

A trial gets a fresh workspace copied from the immutable benchmark package,
runs the agent through the jailed tool layer in a subprocess/container, then
runs an independent verifier. All state transitions, telemetry, evidence and
artifact hashes are persisted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import models
from .agents import get_agent
from .benchmarks import discover
from .classification import classify_detailed
from .config import get_settings
from .providers import build_provider
from .sandbox import run_in_docker
from .security import redact
from .tools import ToolContext
from .verifiers import VERIFIERS

_RUNNING: dict[int, subprocess.Popen] = {}
_RUNNING_LOCK = threading.Lock()
_EXPERIMENT_LOCKS: dict[int, threading.Lock] = {}
_EXPERIMENT_LOCKS_GUARD = threading.Lock()


def _experiment_lock(experiment_id: int) -> threading.Lock:
    with _EXPERIMENT_LOCKS_GUARD:
        return _EXPERIMENT_LOCKS.setdefault(experiment_id, threading.Lock())


def _agent_input(manifest, task_id, agent_kind, provider_cfg, ws, timeout, agent_config):
    return {
        "workspace": str(ws),
        "task_id": task_id,
        "instruction": manifest.get("instruction", ""),
        "prohibited_paths": manifest.get("prohibited_paths", []),
        "allowed_tools": manifest.get("tools", None),
        "allowed_commands": manifest.get("allowed_commands", ["python3 --version"]),
        "max_file_bytes": (manifest.get("resource_limits") or {}).get("max_file_bytes", 1_000_000),
        "timeout_sec": int(timeout),
        "agent_kind": agent_kind,
        "agent_config": agent_config or {},
        "provider_cfg": provider_cfg or {},
        "manifest": {k: v for k, v in manifest.items() if not k.startswith("private") and k != "_dir"},
    }


def _run_agent_subprocess(manifest, task_id, agent_kind, provider_cfg, ws, artifact,
                          timeout=60, agent_config=None, trial_id=None):
    """Run one agent in a child process; hard-kill the process group on timeout."""
    artifact = Path(artifact)
    artifact.mkdir(parents=True, exist_ok=True)
    inp_path, out_path = artifact / "agent_input.json", artifact / "agent_output.json"
    inp = _agent_input(manifest, task_id, agent_kind, provider_cfg, ws, timeout, agent_config)
    inp_path.write_text(json.dumps(inp))
    backend_dir = str(Path(__file__).resolve().parents[1])
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(ws),
        "PYTHONPATH": backend_dir,
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
    }
    key_env = (provider_cfg or {}).get("api_key_env")
    if agent_kind == "llm" and key_env and key_env in os.environ:
        env[key_env] = os.environ[key_env]
    # Resource limits are applied by the child (trial_worker) itself. Using
    # preexec_fn here would be unsafe in a multi-threaded parent process.
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.trial_worker", str(inp_path), str(out_path)],
        env=env, cwd=str(ws), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    if trial_id is not None:
        with _RUNNING_LOCK:
            _RUNNING[trial_id] = proc
    try:
        try:
            _, stderr = proc.communicate(timeout=float(timeout))
        except subprocess.TimeoutExpired:
            _kill_process(proc)
            return {"timed_out": True, "trajectory": [], "permission_attempts": [], "stderr": "timeout"}
        if not out_path.exists():
            return {"timed_out": False,
                    "error": f"trial_worker produced no output (exit {proc.returncode}): {redact(stderr)[-600:]}",
                    "trajectory": [], "permission_attempts": [], "stderr": redact(stderr)[-800:]}
        data = json.loads(out_path.read_text())
        if stderr:
            data.setdefault("stderr", redact(stderr)[-800:])
        return data
    finally:
        if trial_id is not None:
            with _RUNNING_LOCK:
                _RUNNING.pop(trial_id, None)


def _kill_process(proc):
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _event(db, trial, event, detail=""):
    db.add(models.TrialEvent(trial_id=trial.id, event=event, detail=redact(str(detail))[:1000]))
    db.commit()


def _task_lookup():
    return {m["task_id"]: m for m in discover()}


def _provider_config(agent_row) -> dict:
    try:
        cfg = json.loads(agent_row.config or "{}")
    except Exception:
        cfg = {}
    return cfg.get("provider", {}) if isinstance(cfg.get("provider"), dict) else {}


def _agent_config(agent_row) -> dict:
    try:
        cfg = json.loads(agent_row.config or "{}")
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def run_trial(db, trial: models.Trial, force: bool = False) -> models.Trial:
    settings = get_settings()
    trial = db.get(models.Trial, trial.id)
    if trial.status == "completed" and not force:
        return trial
    bench = db.get(models.Benchmark, trial.benchmark_id)
    agent_row = db.get(models.Agent, trial.agent_id)
    if not bench or not agent_row:
        trial.status = "failed"
        trial.failure_category = "infrastructure_failure"
        trial.error = "Missing benchmark or agent row"
        db.commit()
        return trial
    tasks = _task_lookup()
    manifest = tasks.get(bench.task_id)
    artifact = Path(settings.resolved(settings.artifact_dir)) / f"exp-{trial.experiment_id}" / f"trial-{trial.id}"
    ws = artifact / "workspace"
    trial.artifact_dir = str(artifact)
    trial.cancellation_requested = False
    trial.status = "preparing"
    trial.error = ""
    trial.reward = None
    trial.passed = None
    trial.failure_category = "none"
    trial.failure_detail = ""
    db.commit()
    _event(db, trial, "preparing", f"artifact={artifact}")
    start = time.time()
    ctx = None
    result = None
    vres = None
    exc = None

    try:
        if manifest is None:
            raise RuntimeError(f"Benchmark files not found for {bench.task_id}")
        src_ws = Path(manifest["_dir"]) / "workspace"
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True)
        if src_ws.exists():
            shutil.copytree(src_ws, ws, dirs_exist_ok=True, symlinks=False)
        trial.status = "running"
        trial.started_at = dt.datetime.now(dt.UTC)
        db.commit()
        _event(db, trial, "running", "fresh workspace prepared")

        agent_cfg = _agent_config(agent_row)
        allowed_tools = manifest.get("tools")
        ctx = ToolContext(
            ws, bench.task_id, prohibited=manifest.get("prohibited_paths", []),
            allowed_tools=allowed_tools, allowed_commands=manifest.get("allowed_commands"),
            max_file_bytes=(manifest.get("resource_limits") or {}).get("max_file_bytes", 1_000_000),
            manifest=manifest,
        )
        timeout = min(int(manifest.get("timeout_sec", settings.trial_timeout_sec)), settings.trial_timeout_sec)
        mode = settings.execution_mode
        if agent_row.kind == "llm":
            pcfg = _provider_config(agent_row)
            provider = build_provider(
                pcfg.get("provider_type", "mock"), pcfg.get("base_url", ""),
                pcfg.get("model", agent_row.model), pcfg.get("api_key_env", ""),
                pcfg.get("params") or {},
            )
        else:
            pcfg, provider = {}, None

        if mode == "subprocess":
            out = _run_agent_subprocess(
                manifest, bench.task_id, agent_row.kind, pcfg, ws, artifact, timeout,
                agent_config=agent_cfg, trial_id=trial.id,
            )
            ctx.trajectory = out.get("trajectory", [])
            ctx.permission_attempts = out.get("permission_attempts", [])
            if out.get("timed_out"):
                trial.status = "timed_out"
                trial.error = "Hard timeout: process group killed"
            elif out.get("infrastructure_error"):
                raise RuntimeError(out["infrastructure_error"])
            elif out.get("error"):
                raise RuntimeError(out["error"])
            else:
                result = out
        elif mode == "docker":
            inp = _agent_input(manifest, bench.task_id, agent_row.kind, pcfg, ws, timeout, agent_cfg)
            inp["workspace"] = "/workspace"
            inp_path = artifact / "agent_input.json"
            inp_path.write_text(json.dumps(inp))
            out = run_in_docker(
                ws, artifact, trial.id, timeout,
                memory_mb=(manifest.get("resource_limits") or {}).get("memory_mb", 512),
                cpus=(manifest.get("resource_limits") or {}).get("cpu", 1),
                api_key_env=pcfg.get("api_key_env") if agent_row.kind == "llm" else None,
            )
            ctx.trajectory = out.get("trajectory", [])
            ctx.permission_attempts = out.get("permission_attempts", [])
            if out.get("timed_out"):
                trial.status = "timed_out"
                trial.error = "Container timeout: removed"
            elif out.get("infrastructure_error"):
                raise RuntimeError(out["infrastructure_error"])
            elif out.get("error"):
                raise RuntimeError(out["error"])
            else:
                result = out
        else:
            agent = get_agent(agent_row.kind, provider=provider, config=agent_cfg)
            result_obj = agent.run(ctx, {**manifest, "task_id": bench.task_id}, ws)
            result = {
                "notes": result_obj.notes, "input_tokens": result_obj.input_tokens,
                "output_tokens": result_obj.output_tokens,
                "estimated_cost_usd": result_obj.estimated_cost_usd,
                "cost_provenance": result_obj.cost_provenance,
                "error_kind": result_obj.error_kind,
                "status": result_obj.status,
            }
            if time.time() - start > timeout:
                trial.status = "timed_out"
                trial.error = "Soft timeout: local mode cannot preempt agent code"

        if result and result.get("status") == "budget_exhausted":
            trial.status = "budget_exhausted"
            trial.error = result.get("notes", "Budget exhausted")
        elif result and result.get("error_kind") == "budget_exhaustion":
            trial.status = "budget_exhausted"

        if trial.cancellation_requested or trial.status == "cancelled":
            trial.status = "cancelled"
        else:
            terminal_status = trial.status if trial.status in ("timed_out", "budget_exhausted") else None
            trial.status = "verifying"
            db.commit()
            _event(db, trial, "verifying", "independent verifier started")
            verifier_fn = VERIFIERS.get(manifest.get("verifier", ""))
            if verifier_fn is None:
                raise RuntimeError(f"Unknown verifier {manifest.get('verifier')}")
            vres = verifier_fn(ws, ctx)
            trial.reward, trial.passed = vres["reward"], bool(vres["passed"])
            trial.verifier_evidence = json.dumps(vres)
            trial.verifier_version = str(vres.get("verifier_version", "1"))
            if terminal_status:
                trial.status = terminal_status
                trial.passed = False
            else:
                trial.status = "completed"
            if result:
                trial.input_tokens = result.get("input_tokens")
                trial.output_tokens = result.get("output_tokens")
                trial.estimated_cost_usd = result.get("estimated_cost_usd")
                trial.cost_provenance = result.get("cost_provenance", "unknown")
    except Exception as e:
        exc = e
        trial.status = "failed"
        trial.error = redact(str(e))[:1000]
        traceback.print_exc()
    finally:
        latency = round((time.time() - start) * 1000, 2)
        trial.latency_ms = latency
        info = classify_detailed(trial.status, vres, ctx, exc)
        if trial.status in ("timed_out", "cancelled", "budget_exhausted"):
            if trial.status == "timed_out":
                info = {"category": "timeout", "detail": trial.error or "Timeout", "confidence": 1.0, "rule": "status.timeout"}
            elif trial.status == "cancelled":
                info = {"category": "unclassified", "detail": "Cancelled by operator", "confidence": 1.0, "rule": "status.cancelled"}
            else:
                info = {"category": "budget_exhaustion", "detail": trial.error or "Budget exhausted", "confidence": 0.95, "rule": "status.budget"}
        trial.failure_category = info["category"]
        trial.failure_detail = redact(info.get("detail", ""))[:1000]
        trial.classification_source = "rule"
        trial.classification_confidence = info.get("confidence")
        if vres:
            trial.verifier_evidence = json.dumps(vres)
        artifact.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "agent": agent_row.name, "agent_version": agent_row.version, "agent_kind": agent_row.kind,
            "model": agent_row.model, "provider": agent_row.provider,
            "agent_config_sha256": hashlib.sha256(agent_row.config.encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256((agent_row.prompt or "").encode()).hexdigest(),
            "benchmark": bench.task_id, "benchmark_version": bench.version,
            "content_hash": bench.content_hash, "execution_mode": settings.execution_mode,
            "seed": trial.experiment.seed if trial.experiment else None,
            "trial_repetition": trial.repetition,
        }
        trial.config_snapshot = json.dumps(snapshot)
        # Artifact manifest and size cap.
        files, total = [], 0
        for p in artifact.rglob("*"):
            if p.is_file() and p.name not in ("agent_output.json",):
                size = p.stat().st_size
                total += size
                files.append({"path": str(p.relative_to(artifact)), "bytes": size,
                              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        trial.artifact_bytes = total
        (artifact / "artifact_manifest.json").write_text(json.dumps({"files": files, "total_bytes": total,
                                                                     "limit_bytes": settings.max_artifact_bytes}, indent=2))
        if total > settings.max_artifact_bytes and trial.status == "completed":
            trial.status = "failed"
            trial.passed = False
            trial.failure_category = "resource_exhaustion"
            trial.failure_detail = f"Artifact size {total} exceeds limit {settings.max_artifact_bytes}"
        if result:
            trial.input_tokens = result.get("input_tokens")
            trial.output_tokens = result.get("output_tokens")
            trial.estimated_cost_usd = result.get("estimated_cost_usd")
            trial.cost_provenance = result.get("cost_provenance", "unknown")
        traj = {
            "schema": "agentevalops.trajectory/v1",
            "trial_id": trial.id, "experiment_id": trial.experiment_id,
            "benchmark": bench.task_id, "agent": agent_row.name, "agent_version": agent_row.version,
            "latency_ms": latency, "failure_category": trial.failure_category,
            "failure_detail": trial.failure_detail, "error": trial.error,
            "steps": ctx.trajectory if ctx else [],
            "permission_attempts_blocked": ctx.permission_attempts if ctx else [],
            "verifier": vres or {},
            "final_metrics": {"reward": trial.reward, "passed": trial.passed,
                              "input_tokens": trial.input_tokens, "output_tokens": trial.output_tokens,
                              "estimated_cost_usd": trial.estimated_cost_usd},
            "config": snapshot,
        }
        tp = artifact / "trajectory.json"
        tp.write_text(json.dumps(traj, indent=2))
        trial.trajectory_path = str(tp)
        trial.finished_at = dt.datetime.now(dt.UTC)
        db.commit()
        _event(db, trial, "finished", f"status={trial.status} reward={trial.reward} category={trial.failure_category}")
    return trial


def retry_trial(db, trial: models.Trial) -> models.Trial:
    trial.status = "queued"
    trial.cancellation_requested = False
    trial.error = ""
    db.commit()
    return run_trial(db, trial, force=True)


def cancel_trial(db, trial: models.Trial) -> models.Trial:
    trial.cancellation_requested = True
    if trial.status in ("queued", "preparing"):
        trial.status = "cancelled"
        trial.failure_category = "unclassified"
        trial.failure_detail = "Cancelled before execution"
        trial.finished_at = dt.datetime.now(dt.UTC)
        db.commit()
    elif trial.status == "running":
        with _RUNNING_LOCK:
            proc = _RUNNING.get(trial.id)
        if proc:
            _kill_process(proc)
        trial.status = "cancelled"
        trial.failure_detail = "Cancelled by operator"
        trial.finished_at = dt.datetime.now(dt.UTC)
        db.commit()
    _event(db, trial, "cancelled", f"previous_status={trial.status}")
    return trial


def cancel_experiment(db, experiment: models.Experiment) -> models.Experiment:
    trials = db.query(models.Trial).filter_by(experiment_id=experiment.id).all()
    for trial in trials:
        if trial.status in ("queued", "preparing", "running"):
            cancel_trial(db, trial)
    experiment.status = "cancelled"
    db.commit()
    return experiment


def run_experiment(db, experiment: models.Experiment, retry_failed: bool = False) -> models.Experiment:
    """Execute all runnable trials with bounded concurrency.

    A per-experiment lock makes repeated submissions non-destructive: a second
    call while running returns the current experiment without duplicating work.
    """
    settings = get_settings()
    lock = _experiment_lock(experiment.id)
    if not lock.acquire(blocking=False):
        db.refresh(experiment)
        return experiment
    try:
        db.refresh(experiment)
        if experiment.status == "completed" and not retry_failed:
            return experiment
        experiment.status = "running"
        experiment.started_at = experiment.started_at or dt.datetime.now(dt.UTC)
        db.commit()
        statuses = ("queued", "cancelled") if retry_failed else ("queued",)
        if retry_failed:
            statuses = ("queued", "cancelled", "failed", "timed_out", "infrastructure_failure")
        trials = db.query(models.Trial).filter(
            models.Trial.experiment_id == experiment.id,
            models.Trial.status.in_(statuses),
        ).all()
        ids = [t.id for t in trials]

        def _run(tid):
            from .database import SessionLocal
            session = SessionLocal()
            try:
                t = session.get(models.Trial, tid)
                if t and t.status in statuses:
                    run_trial(session, t, force=retry_failed)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=max(1, settings.max_concurrency)) as pool:
            list(pool.map(_run, ids))
        db.expire_all()
        db.refresh(experiment)
        done = db.query(models.Trial).filter_by(experiment_id=experiment.id).all()
        failed_infra = [t for t in done if t.status in ("failed", "infrastructure_failure", "provider_failure")]
        if all(t.status in ("completed", "failed", "timed_out", "cancelled", "budget_exhausted") for t in done):
            experiment.status = "completed_with_errors" if failed_infra else "completed"
        else:
            experiment.status = "failed"
        experiment.finished_at = dt.datetime.now(dt.UTC)
        db.commit()
        return experiment
    finally:
        lock.release()
