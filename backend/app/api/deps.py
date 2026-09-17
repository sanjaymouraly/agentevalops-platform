"""Shared API helpers."""
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..security import redact, resolve_role


def current_auth(x_api_key: str | None = Header(default=None)):
    return resolve_role(x_api_key)


def audit(db: Session, auth, action: str, resource: str = "", detail: str = ""):
    actor, role = auth
    db.add(models.AuditLog(actor=actor, role=role, action=action, resource=str(resource)[:200],
                           detail=redact(str(detail))[:1000]))
    db.commit()


def get_agent_or_404(db: Session, agent_id: int) -> models.Agent:
    agent = db.get(models.Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return agent


def get_benchmark_or_404(db: Session, benchmark_id: int) -> models.Benchmark:
    bench = db.get(models.Benchmark, benchmark_id)
    if not bench:
        raise HTTPException(404, f"Benchmark {benchmark_id} not found")
    return bench


def get_experiment_or_404(db: Session, experiment_id: int) -> models.Experiment:
    experiment = db.get(models.Experiment, experiment_id)
    if not experiment:
        raise HTTPException(404, f"Experiment {experiment_id} not found")
    return experiment


def get_report_or_404(db: Session, report_id: int) -> models.ReleaseReport:
    report = db.get(models.ReleaseReport, report_id)
    if not report:
        raise HTTPException(404, f"Report {report_id} not found")
    return report


def get_trial_or_404(db: Session, trial_id: int) -> models.Trial:
    trial = db.get(models.Trial, trial_id)
    if not trial:
        raise HTTPException(404, f"Trial {trial_id} not found")
    return trial
