"""JSON serializers shared by API routers."""
from __future__ import annotations

import json
from typing import Any


def _json(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def benchmark_out(b) -> dict:
    return {
        "id": b.id, "task_id": b.task_id, "version": b.version, "name": b.name,
        "description": b.description, "difficulty": b.difficulty, "category": b.category,
        "tags": _json(b.tags, []), "instruction": b.instruction, "content_hash": b.content_hash,
        "archived": b.archived, "source": b.source, "manifest": _json(b.manifest, {}),
        "created_at": _dt(b.created_at),
    }


def agent_out(a) -> dict:
    return {
        "id": a.id, "name": a.name, "kind": a.kind, "version": a.version,
        "provider": a.provider, "model": a.model, "prompt": a.prompt,
        "system_prompt": a.system_prompt, "tools": _json(a.tools, []),
        "config": _json(a.config, {}), "description": a.description,
        "archived": a.archived, "created_at": _dt(a.created_at),
    }


def provider_out(p) -> dict:
    return {
        "id": p.id, "name": p.name, "provider_type": p.provider_type, "base_url": p.base_url,
        "model": p.model, "api_key_masked": p.api_key_masked, "api_key_env": p.api_key_env,
        "params": _json(p.params, {}), "is_default": p.is_default,
        "created_at": _dt(p.created_at), "updated_at": _dt(p.updated_at),
    }


def experiment_out(e) -> dict:
    return {
        "id": e.id, "name": e.name, "description": e.description, "status": e.status,
        "repetitions": e.repetitions, "agent_ids": _json(e.agent_ids, []),
        "benchmark_ids": _json(e.benchmark_ids, []), "seed": e.seed,
        "baseline_experiment_id": e.baseline_experiment_id, "policy": _json(e.policy, {}),
        "created_by": e.created_by, "created_at": _dt(e.created_at),
        "started_at": _dt(e.started_at), "finished_at": _dt(e.finished_at),
    }


def trial_out(t) -> dict:
    return {
        "id": t.id, "experiment_id": t.experiment_id, "benchmark_id": t.benchmark_id,
        "agent_id": t.agent_id, "repetition": t.repetition, "status": t.status,
        "reward": t.reward, "passed": t.passed, "failure_category": t.failure_category,
        "failure_detail": t.failure_detail, "latency_ms": t.latency_ms,
        "input_tokens": t.input_tokens, "output_tokens": t.output_tokens,
        "estimated_cost_usd": t.estimated_cost_usd, "cost_provenance": t.cost_provenance,
        "verifier_evidence": _json(t.verifier_evidence, {}), "verifier_version": t.verifier_version,
        "classification_source": t.classification_source,
        "classification_confidence": t.classification_confidence,
        "reviewer": t.reviewer, "trajectory_path": t.trajectory_path,
        "artifact_dir": t.artifact_dir, "artifact_bytes": t.artifact_bytes,
        "config_snapshot": _json(t.config_snapshot, {}), "error": t.error,
        "cancellation_requested": t.cancellation_requested,
        "created_at": _dt(t.created_at), "started_at": _dt(t.started_at), "finished_at": _dt(t.finished_at),
    }


def event_out(e) -> dict:
    return {"id": e.id, "trial_id": e.trial_id, "ts": _dt(e.ts), "event": e.event, "detail": e.detail}


def report_out(r) -> dict:
    return {
        "id": r.id, "experiment_id": r.experiment_id, "baseline_experiment_id": r.baseline_experiment_id,
        "gate": r.gate_status, "gate_reasons": _json(r.gate_reasons, []), "summary": _json(r.summary, {}),
        "policy": _json(r.policy, {}), "created_by": r.created_by, "created_at": _dt(r.created_at),
        "files": {"markdown": r.markdown_path, "html": r.html_path, "json": r.json_path, "pdf": r.pdf_path},
    }


def approval_out(a) -> dict:
    return {
        "id": a.id, "experiment_id": a.experiment_id, "report_id": a.report_id, "decision": a.decision,
        "approver": a.approver, "role": a.role, "notes": a.notes, "override_gate": a.override_gate,
        "justification": a.justification, "created_at": _dt(a.created_at),
    }


def audit_out(a) -> dict:
    return {
        "id": a.id, "actor": a.actor, "role": a.role, "action": a.action,
        "resource": a.resource, "detail": a.detail, "created_at": _dt(a.created_at),
    }


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
