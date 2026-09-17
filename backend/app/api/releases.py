"""Release reports, downloads and human approval workflow.

A gate result is evidence, not an authorization. Approval is a separate,
role-gated action recorded with an auditable rationale. A failing gate can only
be approved through an explicit, justified override by an approver.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..reports import DEFAULT_POLICY, build_report_data, write_reports
from ..schemas import ApprovalIn, ReportIn
from ..security import require
from ..serializers import approval_out, report_out
from .deps import audit, get_experiment_or_404, get_report_or_404

router = APIRouter(tags=["releases"])


def _maps(db: Session):
    agents = {a.id: {"name": a.name, "version": a.version, "kind": a.kind,
                     "provider": a.provider, "model": a.model} for a in db.query(models.Agent).all()}
    benches = {b.id: {"task_id": b.task_id, "version": b.version, "name": b.name,
                      "category": b.category, "difficulty": b.difficulty} for b in db.query(models.Benchmark).all()}
    return agents, benches


@router.post("/api/v1/experiments/{experiment_id}/report", status_code=201)
def create_report(experiment_id: int, payload: ReportIn | None = None,
                  db: Session = Depends(get_db), auth=Depends(require("operator"))):
    payload = payload or ReportIn()
    experiment = get_experiment_or_404(db, experiment_id)
    baseline_id = payload.baseline_experiment_id or experiment.baseline_experiment_id
    baseline = get_experiment_or_404(db, baseline_id) if baseline_id else None
    agents, benches = _maps(db)
    policy = {**DEFAULT_POLICY, **(json.loads(experiment.policy or "{}")), **(payload.policy or {})}
    data = build_report_data(db, models, experiment, baseline, policy)
    from ..config import get_settings
    settings = get_settings()
    out_dir = settings.resolved(settings.artifact_dir) / f"exp-{experiment.id}" / "reports" / f"report-{models.now().strftime('%Y%m%dT%H%M%S%f')}"
    paths = write_reports(data, out_dir, agents, benches)
    row = models.ReleaseReport(
        experiment_id=experiment.id,
        baseline_experiment_id=baseline.id if baseline else None,
        gate_status=data["gate"],
        gate_reasons=json.dumps(data["gate_reasons"]),
        summary=json.dumps(data["summary"], default=str),
        policy=json.dumps(policy),
        markdown_path=paths["markdown"], html_path=paths["html"],
        json_path=paths["json"], pdf_path=paths["pdf"], created_by=auth[0],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, auth, "report.create", f"experiment-{experiment.id}",
          f"report={row.id} gate={row.gate_status}")
    return {**report_out(row), "report_id": row.id, "gate_reasons": data["gate_reasons"],
            "summary": data["summary"], "regressions": data["regressions"],
            "regression_coverage": data["regression_coverage"],
            "download": {k: f"/api/v1/reports/{row.id}/download?fmt={k}" for k in ("markdown", "html", "json", "pdf")}}


@router.get("/api/v1/reports")
def list_reports(experiment_id: int | None = None, gate: str = "",
                 limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
                 db: Session = Depends(get_db)):
    query = db.query(models.ReleaseReport)
    if experiment_id:
        query = query.filter_by(experiment_id=experiment_id)
    if gate:
        query = query.filter_by(gate_status=gate)
    rows = query.order_by(models.ReleaseReport.id.desc()).all()
    return [report_out(r) for r in rows[offset:offset + limit]]


@router.get("/api/v1/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = get_report_or_404(db, report_id)
    approvals = db.query(models.Approval).filter_by(report_id=report.id).order_by(models.Approval.id.desc()).all()
    return {**report_out(report), "approvals": [approval_out(a) for a in approvals]}


@router.get("/api/v1/reports/{report_id}/download")
def download_report(report_id: int, fmt: str = Query(default="markdown", pattern="^(markdown|html|json|pdf)$"),
                    db: Session = Depends(get_db)):
    report = get_report_or_404(db, report_id)
    path = {"markdown": report.markdown_path, "html": report.html_path,
            "json": report.json_path, "pdf": report.pdf_path}[fmt]
    if not path or not Path(path).is_file():
        raise HTTPException(404, f"{fmt} report file is not available")
    media = {"markdown": "text/markdown", "html": "text/html", "json": "application/json",
             "pdf": "application/pdf"}[fmt]
    suffix = Path(path).suffix or ".txt"
    return FileResponse(path, media_type=media,
                        filename=f"agentevalops-report-{report.id}{suffix}")


@router.post("/api/v1/reports/{report_id}/approve")
def approve(report_id: int, payload: ApprovalIn, db: Session = Depends(get_db),
            auth=Depends(require("approver"))):
    report = get_report_or_404(db, report_id)
    if payload.decision == "approved" and report.gate_status != "PASS":
        if not payload.override_gate:
            raise HTTPException(
                409,
                f"Gate is {report.gate_status}; approval requires override_gate=true and a written justification.",
            )
        if not payload.justification.strip():
            raise HTTPException(422, "An override requires a justification.")
    if payload.decision == "approved" and report.gate_status == "PASS" and payload.override_gate:
        raise HTTPException(422, "override_gate is only meaningful for a non-PASS report.")
    row = models.Approval(
        experiment_id=report.experiment_id, report_id=report.id, decision=payload.decision,
        approver=payload.approver, role=auth[1], notes=payload.notes,
        override_gate=payload.override_gate, justification=payload.justification,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, auth, "report.approve" if payload.decision == "approved" else "report.reject",
          f"report-{report.id}",
          f"gate={report.gate_status} override={payload.override_gate} approver={payload.approver}")
    return {**approval_out(row), "report_gate": report.gate_status}


@router.get("/api/v1/reports/{report_id}/approvals")
def report_approvals(report_id: int, db: Session = Depends(get_db)):
    get_report_or_404(db, report_id)
    rows = db.query(models.Approval).filter_by(report_id=report_id).order_by(models.Approval.id.desc()).all()
    return [approval_out(a) for a in rows]


@router.get("/api/v1/approvals")
def list_approvals(experiment_id: int | None = None, limit: int = Query(default=100, ge=1, le=500),
                   db: Session = Depends(get_db)):
    query = db.query(models.Approval)
    if experiment_id:
        query = query.filter_by(experiment_id=experiment_id)
    rows = query.order_by(models.Approval.id.desc()).limit(limit).all()
    return [approval_out(a) for a in rows]
