import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..execution import cancel_trial, retry_trial
from ..schemas import ClassificationIn
from ..security import require
from ..serializers import event_out, trial_out
from .deps import audit, get_trial_or_404

router = APIRouter(prefix="/api/v1/trials", tags=["trials"])


def _trajectory(trial):
    if not trial.trajectory_path:
        return None
    p = Path(trial.trajectory_path)
    if not p.exists() or not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


@router.get("/{trial_id}")
def get_trial(trial_id: int, db: Session = Depends(get_db)):
    trial = get_trial_or_404(db, trial_id)
    events = db.query(models.TrialEvent).filter_by(trial_id=trial_id).order_by(models.TrialEvent.id).all()
    agent = db.get(models.Agent, trial.agent_id)
    bench = db.get(models.Benchmark, trial.benchmark_id)
    return {**trial_out(trial), "trajectory": _trajectory(trial), "events": [event_out(e) for e in events],
            "agent_name": agent.name if agent else None, "agent_version": agent.version if agent else None,
            "benchmark_task_id": bench.task_id if bench else None, "benchmark_name": bench.name if bench else None}


@router.get("/{trial_id}/trajectory")
def download_trajectory(trial_id: int, db: Session = Depends(get_db)):
    trial = get_trial_or_404(db, trial_id)
    if not trial.trajectory_path or not Path(trial.trajectory_path).exists():
        raise HTTPException(404, "Trajectory not found")
    return FileResponse(trial.trajectory_path, media_type="application/json",
                        filename=f"trial-{trial_id}-trajectory.json")


@router.get("/{trial_id}/artifacts")
def list_artifacts(trial_id: int, db: Session = Depends(get_db)):
    trial = get_trial_or_404(db, trial_id)
    root = Path(trial.artifact_dir) if trial.artifact_dir else None
    if not root or not root.exists():
        return {"files": [], "root": trial.artifact_dir}
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size})
    return {"files": files, "root": str(root), "total_bytes": sum(f["bytes"] for f in files)}


@router.get("/{trial_id}/artifact")
def get_artifact(trial_id: int, path: str = Query(...), db: Session = Depends(get_db)):
    trial = get_trial_or_404(db, trial_id)
    if not trial.artifact_dir:
        raise HTTPException(404, "No artifact directory")
    root = Path(trial.artifact_dir).resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(403, "Path escapes artifact directory")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(target, filename=target.name)


@router.post("/{trial_id}/cancel")
def cancel(trial_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    trial = cancel_trial(db, get_trial_or_404(db, trial_id))
    audit(db, auth, "trial.cancel", f"trial-{trial_id}")
    return trial_out(trial)


@router.post("/{trial_id}/retry")
def retry(trial_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    trial = retry_trial(db, get_trial_or_404(db, trial_id))
    audit(db, auth, "trial.retry", f"trial-{trial_id}", f"status={trial.status}")
    return trial_out(trial)


@router.patch("/{trial_id}/classification")
def correct_classification(trial_id: int, payload: ClassificationIn, db: Session = Depends(get_db),
                           auth=Depends(require("operator"))):
    trial = get_trial_or_404(db, trial_id)
    old = trial.failure_category
    trial.failure_category = payload.failure_category
    trial.classification_source = "reviewer"
    trial.reviewer = payload.reviewer
    trial.classification_confidence = 1.0
    if payload.notes:
        trial.failure_detail = (trial.failure_detail + f" | reviewer: {payload.notes}")[:1000]
    db.commit()
    audit(db, auth, "trial.classification_correct", f"trial-{trial_id}",
          f"{old} -> {payload.failure_category} by {payload.reviewer}")
    return trial_out(trial)
