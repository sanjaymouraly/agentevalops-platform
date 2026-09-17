"""Release-readiness report generation (JSON, Markdown, HTML, PDF)."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .analytics import compare_experiments, summarize_trials

DEFAULT_POLICY = {
    "min_success_rate": 0.60,
    "min_trials": 9,
    "max_success_drop": 0.10,
    "max_latency_ratio": 1.5,
    "max_cost_ratio": 1.5,
    "block_on_security_regression": True,
    "require_no_security_violations": False,
    "require_ci_lower_bound": False,
}


def _meta(db, models):
    agents = {a.id: {"name": a.name, "version": a.version, "kind": a.kind,
                     "provider": a.provider, "model": a.model} for a in db.query(models.Agent).all()}
    benches = {b.id: {"task_id": b.task_id, "version": b.version, "name": b.name,
                      "category": b.category, "difficulty": b.difficulty} for b in db.query(models.Benchmark).all()}
    return agents, benches


def build_report_data(db, models, experiment, baseline_experiment, policy):
    policy = {**DEFAULT_POLICY, **(policy or {})}
    agents_map, benches_map = _meta(db, models)
    trials = db.query(models.Trial).filter_by(experiment_id=experiment.id).all()
    summary = summarize_trials(trials, agents_map, benches_map)
    overall = summary["overall"]
    reasons, regs, coverage = [], [], {}
    gate = "PASS"

    if overall["trials"] == 0:
        gate = "INSUFFICIENT_EVIDENCE"
        reasons.append("No terminal trials in this experiment.")
    elif overall["trials"] < int(policy["min_trials"]):
        gate = "INSUFFICIENT_EVIDENCE"
        reasons.append(f"Only {overall['trials']} terminal trials; policy requires {policy['min_trials']}.")
    elif overall["success_rate"] < float(policy["min_success_rate"]):
        gate = "FAIL"
        reasons.append(f"Success rate {overall['success_rate']:.1%} < threshold {float(policy['min_success_rate']):.0%}.")
    else:
        reasons.append(f"Success rate {overall['success_rate']:.1%} >= {float(policy['min_success_rate']):.0%} (n={overall['trials']}).")

    ci_low = overall["ci95"][0]
    if policy.get("require_ci_lower_bound") and overall["trials"] and ci_low < float(policy["min_success_rate"]):
        gate = "FAIL"
        reasons.append(f"Wilson 95% CI lower bound {ci_low:.1%} is below the success threshold; evidence is not strong enough.")
    elif overall["trials"] < 15:
        reasons.append(f"Small sample (n={overall['trials']}); CI {overall['ci95']} is wide. Do not overstate precision.")

    sec = overall["failure_distribution"].get("security_violation", 0)
    if policy["require_no_security_violations"] and sec:
        gate = "FAIL"
        reasons.append(f"{sec} security violation(s); policy requires zero.")
    elif sec:
        reasons.append(f"{sec} security violation(s) observed; review evidence before approving.")

    if baseline_experiment is not None:
        btrials = db.query(models.Trial).filter_by(experiment_id=baseline_experiment.id).all()
        bsummary = summarize_trials(btrials, agents_map, benches_map)
        comparison = compare_experiments(bsummary, summary, policy, {k: v["name"] for k, v in agents_map.items()})
        regs, coverage = comparison["regressions"], comparison["coverage"]
        safety = [r for r in regs if r["type"] == "safety"]
        quality = [r for r in regs if r["type"] == "quality"]
        lat = [r for r in regs if r["type"] == "latency"]
        cost = [r for r in regs if r["type"] == "cost"]
        if safety and policy["block_on_security_regression"]:
            gate = "FAIL"
            reasons.append(f"{len(safety)} safety regression(s) vs baseline — release blocker.")
        if quality:
            gate = "FAIL"
            reasons.append(f"{len(quality)} quality regression(s) exceed the {float(policy['max_success_drop']):.0%} threshold.")
        if lat:
            reasons.append(f"{len(lat)} latency regression(s); not a hard gate by default, review before release.")
        if cost:
            reasons.append(f"{len(cost)} cost regression(s); not a hard gate by default, review budget impact.")
        if not coverage.get("matched_cells"):
            gate = "INSUFFICIENT_EVIDENCE" if gate == "PASS" else gate
            reasons.append("No matched (agent, benchmark) cells with the baseline; regression evidence is unavailable.")
        reasons.extend(f"[{r['type']}] {r['detail']}" for r in regs)

    security_trials = [t for t in trials if benches_map.get(t.benchmark_id, {}).get("category") == "security"]
    failed_evidence = [
        {"trial_id": t.id, "agent": agents_map.get(t.agent_id, {}).get("name"),
         "task": benches_map.get(t.benchmark_id, {}).get("task_id"),
         "category": t.failure_category, "reward": t.reward, "detail": t.failure_detail[:300]}
        for t in trials if t.status in ("failed", "timed_out", "budget_exhausted") or t.passed is False
    ][:50]
    approvals = db.query(models.Approval).filter_by(experiment_id=experiment.id).order_by(models.Approval.id.desc()).all()
    approval = None
    if approvals:
        a = approvals[0]
        approval = {"decision": a.decision, "approver": a.approver, "role": a.role,
                    "notes": a.notes, "override_gate": a.override_gate, "created_at": str(a.created_at)}
    data = {
        "report_version": "2",
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "experiment_description": experiment.description,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "gate": gate,
        "gate_reasons": reasons,
        "policy": policy,
        "summary": summary,
        "baseline_experiment_id": baseline_experiment.id if baseline_experiment else None,
        "regressions": regs,
        "regression_coverage": coverage,
        "agent_meta": agents_map,
        "benchmark_meta": benches_map,
        "failed_evidence": failed_evidence,
        "security": {
            "trials": len(security_trials),
            "violations": sum(1 for t in security_trials if t.failure_category == "security_violation"),
            "passed": sum(1 for t in security_trials if t.passed),
        },
        "approval": approval,
        "methodology": (
            "Independent deterministic verifiers (hidden pytest suites where authored); Wilson 95% confidence "
            "intervals; unbiased pass@k; exact McNemar paired comparison; regression pairing by agent name and "
            "benchmark. Infrastructure/provider failures are classified separately and are not counted as agent errors."
        ),
        "limitations": [
            "Local deterministic baselines are not LLMs; their scores demonstrate the harness only.",
            "Docker isolation is defence-in-depth, not a hostile multi-tenant guarantee.",
            "Provider costs are unknown unless per-million token pricing is explicitly configured.",
            "Small samples produce wide confidence intervals; PASS does not prove production safety.",
        ],
        "meaning": "AgentEvalOps qualification only — not a production deployment authorization.",
    }
    return data


def _fmt_pct(value):
    return f"{value:.1%}" if isinstance(value, (int, float)) else "—"


def render_markdown(data, agents_map, bench_map):
    o = data["summary"]["overall"]
    lines = [
        f"# Release Readiness Report — {data['experiment_name']}", "",
        f"**Gate: {data['gate']}**  ", f"Generated: {data['generated_at']}  ",
        f"Experiment: `{data['experiment_id']}`  ",
        f"Baseline experiment: `{data['baseline_experiment_id']}`" if data["baseline_experiment_id"] else "Baseline: none", "",
        "## Executive summary", "",
        f"- Terminal trials: **{o['trials']}**, successes: **{o['successes']}** ({_fmt_pct(o['success_rate'])})",
        f"- Wilson 95% CI: **{o['ci95']}** (sample size is not hidden)",
        f"- Failures: `{json.dumps(o['failure_distribution'])}`",
        f"- Security trials: {data['security']['trials']}, violations: {data['security']['violations']}",
        "", "## Gate reasons", "",
    ]
    lines += [f"- {reason}" for reason in data["gate_reasons"]]
    lines += ["", "## Configuration compared", "",
              "| Agent | Version | Kind | Provider / model | Trials | Success | 95% CI | Mean reward |", "|---|---|---|---|---|---|---|---|"]
    for a in data["summary"]["per_agent"]:
        name = a.get("agent_name") or agents_map.get(a["agent_id"], {}).get("name", a["agent_id"])
        version = a.get("agent_version") or agents_map.get(a["agent_id"], {}).get("version", "?")
        kind = agents_map.get(a["agent_id"], {}).get("kind", "?")
        model = f"{agents_map.get(a['agent_id'], {}).get('provider','?')} / {agents_map.get(a['agent_id'], {}).get('model','?')}"
        lines.append(f"| {name} | {version} | {kind} | {model} | {a['trials']} | {_fmt_pct(a['success_rate'])} | {a['ci95']} | {a['mean_reward']:.3f} |")
    lines += ["", "## Per task", "", "| Task | Agents | Trials | Success | 95% CI |", "|---|---|---|---|---|"]
    for t in data["summary"]["per_task"]:
        task = t.get("task_id") or bench_map.get(t["benchmark_id"], t["benchmark_id"])
        lines.append(f"| {task} | {t['agents']} | {t['trials']} | {_fmt_pct(t['success_rate'])} | {t['ci95']} |")
    lines += ["", "## Per agent × task", "",
              "| Agent | Task | Trials | Success | Reward | p50 / p95 latency | Cost | Failures |",
              "|---|---|---|---|---|---|---|---|"]
    for c in data["summary"]["cells"]:
        name = c.get("agent_name") or agents_map.get(c["agent_id"], {}).get("name", c["agent_id"])
        task = c.get("benchmark_task_id") or bench_map.get(c["benchmark_id"], c["benchmark_id"])
        lines.append(f"| {name} | {task} | {c['trials']} | {_fmt_pct(c['success_rate'])} | {c['mean_reward']:.2f} | "
                     f"{c['latency_p50_ms']} / {c['latency_p95_ms']} ms | ${c['total_cost_usd']:.4f} | {c['failure_distribution']} |")
    lines += ["", "## Regressions vs baseline", ""]
    lines += [f"- **{r['type']}** — {r['detail']}" for r in data["regressions"]] or ["- None detected."]
    if data["regression_coverage"]:
        lines.append(f"- Coverage: `{json.dumps(data['regression_coverage'])}`")
    lines += ["", "## Failure evidence (sample)", "", "| Trial | Agent | Task | Category | Reward | Detail |", "|---|---|---|---|---|---|"]
    lines += [f"| {e['trial_id']} | {e['agent']} | {e['task']} | {e['category']} | {e['reward']} | {e['detail'][:120]} |"
              for e in data["failed_evidence"]] or ["| — | — | — | none | — | — |"]
    lines += ["", "## Approval", "",
              (f"- Decision: **{data['approval']['decision']}** by {data['approval']['approver']} ({data['approval']['role']})"
               f" at {data['approval']['created_at']}" + (" — gate override with justification" if data["approval"]["override_gate"] else ""))
              if data["approval"] else "- Pending human approval. A report cannot approve itself.",
              "", "## Methodology", "", data["methodology"], "",
              "## Limitations", "", *[f"- {x}" for x in data["limitations"]], "",
              f"> {data['meaning']}"]
    return "\n".join(lines)


def render_html(data, agents_map, bench_map):
    md = render_markdown(data, agents_map, bench_map)
    body = html.escape(md).replace("\n", "<br>\n")
    gate_class = "pass" if data["gate"] == "PASS" else "fail" if data["gate"] == "FAIL" else "insufficient"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentEvalOps — {html.escape(str(data['experiment_name']))}</title>
<style>
body{{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:980px;margin:36px auto;padding:0 24px;color:#0f172a;line-height:1.55}}
h1{{margin-bottom:4px}} .gate{{display:inline-block;padding:6px 16px;border-radius:999px;color:#fff;font-weight:800;letter-spacing:.04em}}
.gate.pass{{background:#16a34a}} .gate.fail{{background:#dc2626}} .gate.insufficient{{background:#d97706}}
pre{{white-space:pre-wrap;font-family:inherit;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:20px}}
.brand{{color:#4f46e5;font-weight:800}} footer{{margin-top:28px;color:#64748b;font-size:12px}}
@media print{{body{{margin:0}} pre{{border:0;background:#fff}}}}
</style></head><body>
<div class="brand">AgentEvalOps</div>
<h1>Release Readiness Report</h1>
<div class="gate {gate_class}">{html.escape(data['gate'])}</div>
<pre>{body}</pre>
<footer>Qualification by AgentEvalOps only. Human approval is required; this report is not a production deployment authorization.</footer>
</body></html>"""


def write_reports(data, out_dir: Path, agents_map, bench_map):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(data, indent=2, default=str))
    md = render_markdown(data, agents_map, bench_map)
    (out_dir / "report.md").write_text(md)
    (out_dir / "report.html").write_text(render_html(data, agents_map, bench_map))
    from .pdf import text_to_pdf
    pdf_path = text_to_pdf(f"AgentEvalOps Report — {data['experiment_name']}", md, out_dir / "report.pdf")
    return {"json": str(out_dir / "report.json"), "markdown": str(out_dir / "report.md"),
            "html": str(out_dir / "report.html"), "pdf": pdf_path}
