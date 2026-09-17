import json
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..analytics import compare_experiments, summarize_trials
from ..database import get_db
from ..serializers import trial_out
from .deps import get_experiment_or_404

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _meta(db):
    agents = {a.id: {"name": a.name, "version": a.version, "kind": a.kind,
                     "provider": a.provider, "model": a.model} for a in db.query(models.Agent).all()}
    benches = {b.id: {"task_id": b.task_id, "version": b.version, "name": b.name,
                      "category": b.category, "difficulty": b.difficulty} for b in db.query(models.Benchmark).all()}
    return agents, benches


def _trials(db, experiment_id=None):
    q = db.query(models.Trial)
    if experiment_id:
        q = q.filter_by(experiment_id=experiment_id)
    return q.all()


@router.get("/overview")
def overview(experiment_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    agents, benches = _meta(db)
    e = None
    if experiment_id:
        e = get_experiment_or_404(db, experiment_id)
    else:
        e = db.query(models.Experiment).order_by(models.Experiment.id.desc()).first()
    trials = _trials(db, e.id) if e else _trials(db)
    summary = summarize_trials(trials, agents, benches)
    all_trials = _trials(db)
    recent = db.query(models.Experiment).order_by(models.Experiment.id.desc()).limit(8).all()
    reports = db.query(models.ReleaseReport).order_by(models.ReleaseReport.id.desc()).limit(5).all()
    return {
        "experiment": {"id": e.id, "name": e.name, "status": e.status} if e else None,
        "summary": summary,
        "totals": {
            "trials": len(all_trials),
            "experiments": db.query(models.Experiment).count(),
            "benchmarks": db.query(models.Benchmark).filter_by(archived=False).count(),
            "agents": db.query(models.Agent).filter_by(archived=False).count(),
            "reports": db.query(models.ReleaseReport).count(),
            "security_violations": sum(1 for t in all_trials if t.failure_category == "security_violation"),
            "known_cost_usd": round(sum(t.estimated_cost_usd or 0 for t in all_trials), 6),
            "input_tokens": sum(t.input_tokens or 0 for t in all_trials),
            "output_tokens": sum(t.output_tokens or 0 for t in all_trials),
        },
        "failure_distribution": dict(Counter(t.failure_category for t in trials if t.failure_category != "none")),
        "recent_experiments": [{"id": x.id, "name": x.name, "status": x.status,
                                "created_at": x.created_at.isoformat() if x.created_at else None} for x in recent],
        "recent_reports": [{"id": r.id, "experiment_id": r.experiment_id, "gate": r.gate_status,
                            "created_at": r.created_at.isoformat() if r.created_at else None} for r in reports],
        "disclosure": "Local deterministic baselines are not LLM performance. LLM trials are labelled with provider/model/cost provenance.",
    }


@router.get("/failures")
def failures(experiment_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    agents, benches = _meta(db)
    trials = _trials(db, experiment_id)
    terminal = [t for t in trials if t.status in ("completed", "failed", "timed_out", "budget_exhausted", "cancelled")]
    distribution = dict(Counter(t.failure_category for t in terminal))
    return {
        "experiment_id": experiment_id,
        "distribution": distribution,
        "non_none": {k: v for k, v in distribution.items() if k != "none"},
        "trials": [
            {**trial_out(t), "agent_name": agents.get(t.agent_id, {}).get("name"),
             "benchmark_task_id": benches.get(t.benchmark_id, {}).get("task_id")}
            for t in terminal if t.failure_category not in ("none",)
        ],
        "taxonomy": ["incorrect_solution", "assertion_failure", "tool_failure", "invalid_tool_arguments",
                     "reasoning_failure", "security_violation", "timeout", "resource_exhaustion",
                     "budget_exhaustion", "provider_failure", "infrastructure_failure", "nondeterminism", "unclassified"],
        "note": "Classification is rule-based from evidence; reviewer corrections are tracked with classification_source.",
    }


@router.get("/security")
def security(experiment_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    agents, benches = _meta(db)
    sec_ids = {b.id for b in db.query(models.Benchmark).filter_by(category="security").all()}
    trials = [t for t in _trials(db, experiment_id) if t.benchmark_id in sec_ids]
    blocked = 0
    for t in trials:
        try:
            evidence = json.loads(t.verifier_evidence or "{}")
            blocked += len(evidence.get("permission_attempts_blocked") or [])
        except Exception:
            pass
    return {
        "security_trials": len(trials),
        "violations": sum(1 for t in trials if t.failure_category == "security_violation"),
        "passed": sum(1 for t in trials if t.passed),
        "blocked_attempts": blocked,
        "boundary_note": ("Boundaries are enforced by the tool layer (path jail, prohibited prefixes, command allowlist). "
                          "The verifier checks outputs and successful prohibited reads, not agent self-report. "
                          "Synthetic secrets only."),
        "trials": [{**trial_out(t), "agent_name": agents.get(t.agent_id, {}).get("name"),
                    "benchmark_task_id": benches.get(t.benchmark_id, {}).get("task_id")} for t in trials],
    }


@router.get("/regressions")
def regressions(candidate_id: int = Query(...), baseline_id: int = Query(...), db: Session = Depends(get_db)):
    cand = get_experiment_or_404(db, candidate_id)
    base = get_experiment_or_404(db, baseline_id)
    agents, benches = _meta(db)
    cs = summarize_trials(_trials(db, cand.id), agents, benches)
    bs = summarize_trials(_trials(db, base.id), agents, benches)
    comparison = compare_experiments(bs, cs, json.loads(cand.policy or "{}"), {k: v["name"] for k, v in agents.items()})
    for r in comparison["regressions"]:
        r["benchmark_task_id"] = benches.get(r["benchmark_id"], {}).get("task_id")
    return comparison


@router.get("/agents")
def agents_analytics(experiment_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    agents, benches = _meta(db)
    trials = _trials(db, experiment_id)
    return summarize_trials(trials, agents, benches)["per_agent"]


@router.get("/costs")
def costs(db: Session = Depends(get_db)):
    agents, _ = _meta(db)
    trials = _trials(db)
    known = [t for t in trials if t.estimated_cost_usd is not None]
    return {
        "known_cost_usd": round(sum(t.estimated_cost_usd or 0 for t in known), 6),
        "trials_with_known_cost": len(known),
        "trials_with_unknown_cost": len(trials) - len(known),
        "input_tokens": sum(t.input_tokens or 0 for t in trials),
        "output_tokens": sum(t.output_tokens or 0 for t in trials),
        "by_agent": [
            {"agent_id": aid, "agent_name": agents.get(aid, {}).get("name"),
             "cost_usd": round(sum(t.estimated_cost_usd or 0 for t in trials if t.agent_id == aid and t.estimated_cost_usd is not None), 6),
             "unknown_cost_trials": sum(1 for t in trials if t.agent_id == aid and t.estimated_cost_usd is None)}
            for aid in sorted({t.agent_id for t in trials})
        ],
        "note": "Costs are unknown unless pricing is configured; local Ollama runs are labelled zero-cost local inference.",
    }
