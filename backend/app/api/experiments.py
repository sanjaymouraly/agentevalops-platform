import json
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models
from ..analytics import compare_experiments, paired_agent_comparison, summarize_trials
from ..database import SessionLocal, get_db
from ..execution import cancel_experiment, run_experiment
from ..schemas import ExperimentIn
from ..security import require
from ..serializers import experiment_out, trial_out
from .deps import audit, get_benchmark_or_404, get_experiment_or_404

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])
_BACKGROUND: set[int] = set()
_BACKGROUND_LOCK = threading.Lock()


def _meta(db: Session):
    agents = {a.id: {"name": a.name, "version": a.version, "kind": a.kind,
                     "provider": a.provider, "model": a.model} for a in db.query(models.Agent).all()}
    benches = {b.id: {"task_id": b.task_id, "version": b.version, "name": b.name,
                      "category": b.category, "difficulty": b.difficulty} for b in db.query(models.Benchmark).all()}
    return agents, benches


def _detail(db: Session, experiment):
    agents, benches = _meta(db)
    trials = db.query(models.Trial).filter_by(experiment_id=experiment.id).order_by(models.Trial.id).all()
    summary = summarize_trials(trials, agents, benches)
    enriched = []
    for t in trials:
        row = trial_out(t)
        row["agent_name"] = agents.get(t.agent_id, {}).get("name")
        row["agent_version"] = agents.get(t.agent_id, {}).get("version")
        row["benchmark_task_id"] = benches.get(t.benchmark_id, {}).get("task_id")
        row["benchmark_name"] = benches.get(t.benchmark_id, {}).get("name")
        enriched.append(row)
    latest_report = db.query(models.ReleaseReport).filter_by(experiment_id=experiment.id).order_by(models.ReleaseReport.id.desc()).first()
    return {**experiment_out(experiment), "summary": summary, "trials": enriched,
            "agent_meta": agents, "benchmark_meta": benches,
            "latest_report": {"id": latest_report.id, "gate": latest_report.gate_status} if latest_report else None}


def _background_run(experiment_id: int):
    with _BACKGROUND_LOCK:
        if experiment_id in _BACKGROUND:
            return
        _BACKGROUND.add(experiment_id)
    try:
        db = SessionLocal()
        try:
            exp = db.get(models.Experiment, experiment_id)
            if exp:
                run_experiment(db, exp)
        finally:
            db.close()
    finally:
        with _BACKGROUND_LOCK:
            _BACKGROUND.discard(experiment_id)


@router.get("")
def list_experiments(
    response: Response,
    status: str = "",
    q: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.Experiment)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(models.Experiment.id.desc()).all()
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in f"{r.name} {r.description}".lower()]
    response.headers["X-Total-Count"] = str(len(rows))
    agents, benches = _meta(db)
    out = []
    for e in rows[offset:offset + limit]:
        trials = db.query(models.Trial).filter_by(experiment_id=e.id).all()
        summary = summarize_trials(trials, agents, benches)
        report = db.query(models.ReleaseReport).filter_by(experiment_id=e.id).order_by(models.ReleaseReport.id.desc()).first()
        out.append({**experiment_out(e), "overall": summary["overall"], "per_agent": summary["per_agent"],
                    "latest_report": {"id": report.id, "gate": report.gate_status} if report else None,
                    "agent_names": [agents.get(aid, {}).get("name") for aid in json.loads(e.agent_ids or "[]")],
                    "task_ids": [benches.get(bid, {}).get("task_id") for bid in json.loads(e.benchmark_ids or "[]")]})
    return out


@router.post("", status_code=201)
def create_experiment(payload: ExperimentIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    for aid in payload.agent_ids:
        agent = db.get(models.Agent, aid)
        if not agent:
            raise HTTPException(422, f"Agent {aid} not found")
    for bid in payload.benchmark_ids:
        get_benchmark_or_404(db, bid)
    if payload.baseline_experiment_id:
        get_experiment_or_404(db, payload.baseline_experiment_id)
    e = models.Experiment(
        name=payload.name, description=payload.description, repetitions=payload.repetitions,
        agent_ids=json.dumps(payload.agent_ids), benchmark_ids=json.dumps(payload.benchmark_ids),
        seed=payload.seed, baseline_experiment_id=payload.baseline_experiment_id,
        policy=json.dumps(payload.policy), created_by=auth[0], status="created",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    for aid in payload.agent_ids:
        for bid in payload.benchmark_ids:
            for rep in range(1, payload.repetitions + 1):
                db.add(models.Trial(experiment_id=e.id, agent_id=aid, benchmark_id=bid, repetition=rep, status="queued"))
    db.commit()
    count = len(payload.agent_ids) * len(payload.benchmark_ids) * payload.repetitions
    audit(db, auth, "experiment.create", e.name, f"trials={count}")
    return _detail(db, e)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    return _detail(db, get_experiment_or_404(db, experiment_id))


@router.post("/{experiment_id}/run")
def run(experiment_id: int, wait: bool = Query(default=True), retry_failed: bool = Query(default=False),
        db: Session = Depends(get_db), auth=Depends(require("operator"))):
    e = get_experiment_or_404(db, experiment_id)
    if wait:
        e = run_experiment(db, e, retry_failed=retry_failed)
        audit(db, auth, "experiment.run", e.name, f"mode=sync retry_failed={retry_failed} status={e.status}")
        return _detail(db, e)
    if e.status in ("running",):
        return _detail(db, e)
    # Non-blocking local mode: the same DB-backed worker contract, run in a thread.
    e.status = "queued"
    db.commit()
    threading.Thread(target=_background_run, args=(e.id,), daemon=True, name=f"aeo-exp-{e.id}").start()
    audit(db, auth, "experiment.run", e.name, "mode=background")
    return _detail(db, e)


@router.post("/{experiment_id}/cancel")
def cancel(experiment_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    e = get_experiment_or_404(db, experiment_id)
    cancel_experiment(db, e)
    audit(db, auth, "experiment.cancel", e.name)
    return _detail(db, e)


@router.get("/{experiment_id}/trials")
def experiment_trials(
    experiment_id: int,
    status: str = "",
    agent_id: int | None = None,
    benchmark_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    get_experiment_or_404(db, experiment_id)
    query = db.query(models.Trial).filter_by(experiment_id=experiment_id)
    if status:
        query = query.filter_by(status=status)
    if agent_id:
        query = query.filter_by(agent_id=agent_id)
    if benchmark_id:
        query = query.filter_by(benchmark_id=benchmark_id)
    rows = query.order_by(models.Trial.id).all()
    return [trial_out(t) for t in rows[offset:offset + limit]]


@router.get("/{experiment_id}/compare")
def compare(experiment_id: int, baseline_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    cand = get_experiment_or_404(db, experiment_id)
    base_id = baseline_id or cand.baseline_experiment_id
    if not base_id:
        raise HTTPException(422, "No baseline: provide baseline_id or set baseline_experiment_id when creating the experiment")
    base = get_experiment_or_404(db, base_id)
    agents, benches = _meta(db)
    cs = summarize_trials(db.query(models.Trial).filter_by(experiment_id=cand.id).all(), agents, benches)
    bs = summarize_trials(db.query(models.Trial).filter_by(experiment_id=base.id).all(), agents, benches)
    comparison = compare_experiments(bs, cs, cand.policy and json.loads(cand.policy) or {}, {k: v["name"] for k, v in agents.items()})
    return {
        "baseline": {"id": base.id, "name": base.name, "summary": bs},
        "candidate": {"id": cand.id, "name": cand.name, "summary": cs},
        **comparison,
    }


@router.get("/{experiment_id}/agent-compare")
def agent_compare(experiment_id: int, a: int = Query(...), b: int = Query(...), db: Session = Depends(get_db)):
    get_experiment_or_404(db, experiment_id)
    agents, _ = _meta(db)
    trials = db.query(models.Trial).filter_by(experiment_id=experiment_id).all()
    result = paired_agent_comparison(trials, a, b)
    result["agent_a_name"] = agents.get(a, {}).get("name")
    result["agent_b_name"] = agents.get(b, {}).get("name")
    return result
