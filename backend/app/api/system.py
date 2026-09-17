from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..benchmarks import discover
from ..config import get_settings
from ..database import get_db
from ..harbor_adapter import is_harbor_available
from ..providers import provider_catalog
from ..sandbox import POLICY, docker_available, docker_image_available
from .deps import current_auth

router = APIRouter()


@router.get("/health", tags=["system"])
def health():
    s = get_settings()
    return {"status": "ok", "app": s.app_name, "version": s.version}


@router.get("/ready", tags=["system"])
def ready(db: Session = Depends(get_db)):
    s = get_settings()
    return {
        "status": "ready",
        "version": s.version,
        "benchmarks_on_disk": len(discover()),
        "benchmarks_in_db": db.query(models.Benchmark).count(),
        "agents_in_db": db.query(models.Agent).count(),
        "docker_available": docker_available(),
        "docker_runner_image": s.docker_image,
        "docker_runner_image_available": docker_image_available(),
        "harbor_available": is_harbor_available(),
        "execution_mode": s.execution_mode,
        "sandbox_policy": POLICY,
        "anonymous_dev_access": s.allow_anonymous,
        "database": "sqlite" if s.is_sqlite else "postgresql",
    }


@router.get("/api/v1/system", tags=["system"])
def system(db: Session = Depends(get_db)):
    s = get_settings()
    trials = db.query(models.Trial).all()
    status_counts = dict(db.query(models.Trial.status, func.count()).group_by(models.Trial.status).all())
    return {
        "benchmarks": db.query(models.Benchmark).filter_by(archived=False).count(),
        "agents": db.query(models.Agent).filter_by(archived=False).count(),
        "experiments": db.query(models.Experiment).count(),
        "reports": db.query(models.ReleaseReport).count(),
        "approvals": db.query(models.Approval).count(),
        "trials": len(trials),
        "completed_trials": sum(1 for t in trials if t.status in ("completed",)),
        "passed_trials": sum(1 for t in trials if t.passed),
        "failed_trials": sum(1 for t in trials if t.status in ("failed", "timed_out", "budget_exhausted")),
        "security_violations": sum(1 for t in trials if t.failure_category == "security_violation"),
        "providers": db.query(models.ProviderConfig).count(),
        "status_counts": status_counts,
        "docker_available": docker_available(),
        "docker_runner_image_available": docker_image_available(),
        "harbor_available": is_harbor_available(),
        "execution_mode": s.execution_mode,
        "total_input_tokens": sum(t.input_tokens or 0 for t in trials),
        "total_output_tokens": sum(t.output_tokens or 0 for t in trials),
        "known_cost_usd": round(sum(t.estimated_cost_usd or 0 for t in trials), 6),
        "unknown_cost_trials": sum(1 for t in trials if t.estimated_cost_usd is None),
        "demo_data_note": "Local deterministic baselines are not LLM performance.",
        "anonymous_dev_access": s.allow_anonymous,
    }


@router.get("/api/v1/meta", tags=["system"])
def meta(db: Session = Depends(get_db), auth=Depends(current_auth)):
    s = get_settings()
    configured = db.query(models.ProviderConfig).all()
    return {
        "app": s.app_name,
        "version": s.version,
        "actor": auth[0],
        "role": auth[1],
        "providers": provider_catalog(),
        "configured_providers": [{"id": p.id, "name": p.name, "provider_type": p.provider_type,
                                  "model": p.model, "is_default": p.is_default} for p in configured],
        "execution_modes": ["local", "subprocess", "docker"],
        "execution_mode": s.execution_mode,
        "limits": {"max_concurrency": s.max_concurrency, "trial_timeout_sec": s.trial_timeout_sec,
                   "max_artifact_bytes": s.max_artifact_bytes, "retention_days": s.retention_days},
        "monthly_budget_usd": s.monthly_budget_usd,
        "allow_anonymous": s.allow_anonymous,
        "roles": ["viewer", "operator", "approver", "admin"],
        "harbor_available": is_harbor_available(),
        "docker_available": docker_available(),
        "docker_runner_image_available": docker_image_available(),
        "note": "Qualification is not a production deployment authorization.",
    }
