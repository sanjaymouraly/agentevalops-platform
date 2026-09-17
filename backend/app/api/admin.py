"""Operational administration: audit trail, worker queue, retention, Harbor."""
from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..benchmarks import ManifestError, content_hash, load_manifest
from ..config import get_settings
from ..database import get_db
from ..harbor_adapter import import_harbor_task, is_harbor_available, run_harbor_job
from ..sandbox import docker_available, docker_image_available
from ..schemas import CleanupIn, HarborImportIn, HarborRunIn
from ..security import require
from ..serializers import audit_out
from .deps import audit

log = logging.getLogger("agentevalops.admin")
router = APIRouter(tags=["admin"])


@router.get("/api/v1/audit")
def list_audit(action: str = "", actor: str = "", q: str = "",
               limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0),
               db: Session = Depends(get_db), auth=Depends(require("operator"))):
    query = db.query(models.AuditLog)
    if action:
        query = query.filter(models.AuditLog.action.like(f"{action}%"))
    if actor:
        query = query.filter_by(actor=actor)
    rows = query.order_by(models.AuditLog.id.desc()).all()
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in f"{r.action} {r.resource} {r.detail} {r.actor}".lower()]
    return [audit_out(r) for r in rows[offset:offset + limit]]


@router.get("/api/v1/worker/status")
def worker_status(db: Session = Depends(get_db)):
    settings = get_settings()
    counts = dict(db.query(models.Trial.status, func.count()).group_by(models.Trial.status).all())
    running = [{"id": e.id, "name": e.name, "started_at": e.started_at.isoformat() if e.started_at else None}
               for e in db.query(models.Experiment).filter_by(status="running").all()]
    queued = [{"id": e.id, "name": e.name} for e in db.query(models.Experiment).filter_by(status="queued").all()]
    return {
        "trial_status_counts": counts,
        "queue_depth": counts.get("queued", 0),
        "running_experiments": running,
        "queued_experiments": queued,
        "execution_mode": settings.execution_mode,
        "max_concurrency": settings.max_concurrency,
        "trial_timeout_sec": settings.trial_timeout_sec,
        "docker_available": docker_available(),
        "docker_runner_image_available": docker_image_available(),
        "harbor_available": is_harbor_available(),
        "note": "Background execution is an in-process thread pool by default. Use the worker_runner CLI or a queue for production.",
    }


def _artifact_roots(db: Session) -> set[Path]:
    roots = set()
    for t in db.query(models.Trial).filter(models.Trial.artifact_dir != "").all():
        roots.add(Path(t.artifact_dir))
    for r in db.query(models.ReleaseReport).all():
        for p in (r.markdown_path, r.html_path, r.json_path, r.pdf_path):
            if p:
                roots.add(Path(p).parent)
    return roots


@router.post("/api/v1/admin/cleanup")
def cleanup(payload: CleanupIn, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    settings = get_settings()
    cutoff = models.now() - __import__("datetime").timedelta(days=payload.older_than_days)
    terminal = ("completed", "failed", "timed_out", "cancelled", "budget_exhausted")
    candidates = []
    for t in db.query(models.Trial).filter(models.Trial.finished_at.isnot(None),
                                           models.Trial.finished_at < cutoff).all():
        if t.status not in terminal or not t.artifact_dir:
            continue
        p = Path(t.artifact_dir)
        if p.exists() and p.is_dir():
            candidates.append({"trial_id": t.id, "path": str(p),
                               "bytes": sum(f.stat().st_size for f in p.rglob("*") if f.is_file())})
    removed = []
    if not payload.dry_run:
        for item in candidates:
            p = Path(item["path"])
            try:
                if p.exists() and settings.resolved(settings.artifact_dir) in p.resolve().parents:
                    shutil.rmtree(p)
                    removed.append(item)
            except Exception as exc:
                log.warning("cleanup skipped %s: %s", p, exc)
        # Orphaned artifact directories (e.g. deleted rows) older than cutoff.
        root = settings.resolved(settings.artifact_dir)
        if root.exists():
            for exp_dir in root.glob("exp-*"):
                try:
                    old = __import__("datetime").datetime.fromtimestamp(
                        exp_dir.stat().st_mtime, __import__("datetime").UTC) < cutoff
                    orphaned = exp_dir.is_dir() and old and not db.query(models.Trial).filter(
                        models.Trial.artifact_dir.like(f"{exp_dir}%")).first()
                    if orphaned:
                        shutil.rmtree(exp_dir)
                except Exception as exc:
                    log.warning("orphan cleanup skipped %s: %s", exp_dir, exc)
        audit(db, auth, "admin.cleanup", "artifacts",
              f"days={payload.older_than_days} removed={len(removed)}")
    return {
        "dry_run": payload.dry_run,
        "older_than_days": payload.older_than_days,
        "candidates": candidates,
        "removed": removed if not payload.dry_run else [],
        "candidate_bytes": sum(c["bytes"] for c in candidates),
        "note": "Database rows and audit records are retained. Only artifact/report files are deleted.",
    }


@router.get("/api/v1/usage")
def usage(db: Session = Depends(get_db)):
    rows = db.query(models.Trial).all()
    by_agent = Counter()
    cost = 0.0
    unknown = 0
    for t in rows:
        try:
            cfg = json.loads(t.config_snapshot or "{}")
        except Exception:
            cfg = {}
        by_agent[(cfg.get("agent"), cfg.get("provider"), cfg.get("model"))] += 1
        if t.estimated_cost_usd is None:
            unknown += 1
        else:
            cost += t.estimated_cost_usd
    return {
        "known_cost_usd": round(cost, 6),
        "unknown_cost_trials": unknown,
        "input_tokens": sum(t.input_tokens or 0 for t in rows),
        "output_tokens": sum(t.output_tokens or 0 for t in rows),
        "trials_by_agent": [
            {"agent": k[0], "provider": k[1], "model": k[2], "trials": v}
            for k, v in sorted(by_agent.items(), key=lambda kv: str(kv[0]))
        ],
        "monthly_budget_usd": get_settings().monthly_budget_usd,
        "disclosure": "Costs are unknown unless pricing is configured. Local Ollama inference is zero API cost.",
    }


@router.get("/api/v1/harbor/status")
def harbor_status():
    return {
        "available": is_harbor_available(),
        "detail": ("Harbor CLI detected." if is_harbor_available()
                   else "Harbor CLI not installed. Native execution and Harbor export work without it."),
        "format": "harbor-framework task directory (task.toml, instruction.md, environment/, tests/test.sh)",
    }


@router.post("/api/v1/harbor/import", status_code=201)
def harbor_import(payload: HarborImportIn, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    src = Path(payload.harbor_task_dir).expanduser().resolve()
    if not src.is_dir():
        raise HTTPException(404, f"Harbor task directory not found: {src}")
    settings = get_settings()
    dest_root = settings.resolved(settings.benchmark_dir)
    try:
        manifest = import_harbor_task(src, dest_root)
        load_manifest(dest_root / manifest["task_id"])
    except (ValueError, ManifestError, FileNotFoundError) as e:
        raise HTTPException(422, f"Harbor import failed: {e}")
    row = db.query(models.Benchmark).filter_by(task_id=manifest["task_id"],
                                               version=manifest["version"]).first()
    if row:
        raise HTTPException(409, "This Harbor task version already exists (immutable)")
    m = load_manifest(dest_root / manifest["task_id"])
    row = models.Benchmark(
        task_id=m["task_id"], version=m["version"], name=m["name"],
        description=m.get("description", ""), difficulty=m["difficulty"], category=m["category"],
        tags=json.dumps(m.get("tags", [])), instruction=m.get("instruction", ""),
        manifest=json.dumps({k: v for k, v in m.items() if k != "_dir"}),
        content_hash=content_hash(dest_root / m["task_id"]), source="harbor",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, auth, "harbor.import", row.task_id, f"from={src}")
    return {"id": row.id, "task_id": row.task_id, "version": row.version,
            "warning": "Review verifier mapping and hidden tests before trusting scores."}


@router.post("/api/v1/harbor/run")
def harbor_run(payload: HarborRunIn, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    args = payload.args
    if len(args) > 20 or any(len(a) > 200 for a in args):
        raise HTTPException(422, "Too many or too-long Harbor arguments")
    if any(a.startswith("--") and a not in ("--help", "--version", "--json", "--yes", "--no-color") for a in args):
        raise HTTPException(422, "Only a small allowlist of Harbor flags is accepted by this demo endpoint")
    try:
        result = run_harbor_job(*args, timeout=60)
    except Exception as e:
        raise HTTPException(502, f"Harbor invocation failed: {e}")
    audit(db, auth, "harbor.run", " ".join(args)[:200])
    return result


@router.get("/api/v1/admin/security-policy")
def security_policy(auth=Depends(require("operator"))):
    from ..sandbox import POLICY
    settings = get_settings()
    return {
        "sandbox": POLICY,
        "execution_mode": settings.execution_mode,
        "anonymous_dev_access": settings.allow_anonymous,
        "api_keys_configured": {
            "admin": bool(settings.admin_key),
            "approver": bool(settings.approver_key),
            "operator": bool(settings.operator_key),
            "viewer": bool(settings.viewer_key),
        },
        "secret_storage": "Provider keys are read from server environment variables only; the database stores a masked hint.",
        "recommendation": "Set AGENTEVALOPS_ALLOW_ANONYMOUS=false and unique keys before any network exposure.",
    }
