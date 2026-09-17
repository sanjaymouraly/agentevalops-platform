"""Evaluation analytics: success, uncertainty, pass@k, cost, reliability,
paired comparisons and regression detection.

Weak evidence is labelled as such. The confidence interval and sample size are
always returned alongside a point estimate.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

TERMINAL = ("completed", "failed", "timed_out", "budget_exhausted", "cancelled")


def Wilson(successes, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / d
    return (round(max(0, centre - half), 4), round(min(1, centre + half), 4))


def pass_at_k(n, successes, k):
    """Unbiased pass@k estimator (Chen et al.) where k <= n."""
    if n == 0 or k > n:
        return None
    if n - successes < k:
        return 1.0
    return round(1.0 - math.comb(n - successes, k) / math.comb(n, k), 4)


def percentile(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return round(s[idx], 2)


def _stdev(vals):
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))


def summarize_trials(trials, agent_meta=None, bench_meta=None):
    """Aggregate trials into cells, per-agent, per-task and overall summaries."""
    agent_meta = agent_meta or {}
    bench_meta = bench_meta or {}
    groups = defaultdict(list)
    for t in trials:
        groups[(t.agent_id, t.benchmark_id)].append(t)
    cells = []
    for (aid, bid), ts in sorted(groups.items()):
        done = [t for t in ts if t.status in TERMINAL]
        succ = sum(1 for t in done if t.passed)
        n = len(done)
        lo, hi = Wilson(succ, n)
        rewards = [t.reward for t in done if t.reward is not None]
        lats = [t.latency_ms for t in done if t.latency_ms is not None]
        costs = [t.estimated_cost_usd for t in done if t.estimated_cost_usd is not None]
        succ_costs = [t.estimated_cost_usd for t in done if t.passed and t.estimated_cost_usd is not None]
        in_tok = sum(t.input_tokens or 0 for t in done)
        out_tok = sum(t.output_tokens or 0 for t in done)
        std = _stdev(rewards)
        meta_a = agent_meta.get(aid, {}) if isinstance(agent_meta.get(aid), dict) else {}
        meta_b = bench_meta.get(bid, {}) if isinstance(bench_meta.get(bid), dict) else {}
        cells.append({
            "agent_id": aid, "benchmark_id": bid,
            "agent_name": meta_a.get("name"), "agent_version": meta_a.get("version"),
            "benchmark_task_id": meta_b.get("task_id"),
            "trials": n, "successes": succ,
            "success_rate": round(succ / n, 4) if n else 0.0, "ci95": [lo, hi],
            "pass_at_1": pass_at_k(n, succ, 1), "pass_at_3": pass_at_k(n, succ, min(3, n)) if n else None,
            "mean_reward": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
            "std_reward": round(std, 4), "consistency": round(max(0.0, 1 - std), 4),
            "latency_p50_ms": percentile(lats, 0.5), "latency_p95_ms": percentile(lats, 0.95),
            "total_cost_usd": round(sum(costs), 6) if costs else 0.0,
            "cost_per_success_usd": round(sum(succ_costs) / succ, 6) if succ and succ_costs else None,
            "input_tokens": in_tok, "output_tokens": out_tok,
            "failure_distribution": dict(Counter(t.failure_category for t in done)),
            "status_distribution": dict(Counter(t.status for t in done)),
        })
    terminal = [t for t in trials if t.status in TERMINAL]
    succ = sum(1 for t in terminal if t.passed)
    lo, hi = Wilson(succ, len(terminal))
    overall = {
        "trials": len(terminal), "successes": succ,
        "success_rate": round(succ / len(terminal), 4) if terminal else 0.0,
        "ci95": [lo, hi],
        "failure_distribution": dict(Counter(t.failure_category for t in terminal)),
        "status_distribution": dict(Counter(t.status for t in terminal)),
        "total_cost_usd": round(sum(t.estimated_cost_usd for t in terminal if t.estimated_cost_usd is not None), 6),
        "input_tokens": sum(t.input_tokens or 0 for t in terminal),
        "output_tokens": sum(t.output_tokens or 0 for t in terminal),
        "latency_p50_ms": percentile([t.latency_ms for t in terminal if t.latency_ms is not None], 0.5),
        "latency_p95_ms": percentile([t.latency_ms for t in terminal if t.latency_ms is not None], 0.95),
    }
    # Per-agent and per-task rollups.
    per_agent = []
    for aid in sorted({c["agent_id"] for c in cells}):
        cs = [c for c in cells if c["agent_id"] == aid]
        n = sum(c["trials"] for c in cs)
        s = sum(c["successes"] for c in cs)
        lo, hi = Wilson(s, n)
        rewards = [c["mean_reward"] for c in cs]
        per_agent.append({
            "agent_id": aid, "agent_name": agent_meta.get(aid, {}).get("name") if isinstance(agent_meta.get(aid), dict) else None,
            "agent_version": agent_meta.get(aid, {}).get("version") if isinstance(agent_meta.get(aid), dict) else None,
            "tasks": len(cs), "trials": n, "successes": s,
            "success_rate": round(s / n, 4) if n else 0.0, "ci95": [lo, hi],
            "mean_reward": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
            "cost_usd": round(sum(c["total_cost_usd"] for c in cs), 6),
            "failure_distribution": dict(Counter(k for c in cs for k, v in c["failure_distribution"].items() for _ in range(v))),
        })
    per_task = []
    for bid in sorted({c["benchmark_id"] for c in cells}):
        cs = [c for c in cells if c["benchmark_id"] == bid]
        n = sum(c["trials"] for c in cs)
        s = sum(c["successes"] for c in cs)
        lo, hi = Wilson(s, n)
        per_task.append({
            "benchmark_id": bid, "task_id": bench_meta.get(bid, {}).get("task_id") if isinstance(bench_meta.get(bid), dict) else None,
            "agents": len(cs), "trials": n, "successes": s,
            "success_rate": round(s / n, 4) if n else 0.0, "ci95": [lo, hi],
        })
    return {"overall": overall, "cells": cells, "per_agent": per_agent, "per_task": per_task}


def _cell_key(cell, agent_names):
    agent = cell.get("agent_name") or (agent_names or {}).get(cell["agent_id"]) or cell["agent_id"]
    return (agent, cell["benchmark_id"])


def _aggregate(cells, agent_names=None):
    d = defaultdict(lambda: {"trials": 0, "successes": 0, "latency": [], "cost": 0.0,
                             "failures": Counter(), "versions": set()})
    for c in cells:
        key = _cell_key(c, agent_names)
        d[key]["trials"] += c["trials"]
        d[key]["successes"] += c["successes"]
        if c.get("latency_p50_ms"):
            d[key]["latency"].append(c["latency_p50_ms"])
        d[key]["cost"] += c.get("total_cost_usd") or 0
        d[key]["failures"].update(c.get("failure_distribution") or {})
        if c.get("agent_version"):
            d[key]["versions"].add(str(c["agent_version"]))
    out = {}
    for key, v in d.items():
        out[key] = {"success_rate": v["successes"] / v["trials"] if v["trials"] else 0,
                    "trials": v["trials"], "successes": v["successes"],
                    "latency_p50_ms": max(v["latency"], default=0),
                    "cost": v["cost"], "failures": v["failures"], "versions": sorted(v["versions"])}
    return out


def detect_regressions(baseline_cells, candidate_cells, policy=None, agent_names=None):
    """Compare matched (agent name, benchmark) cells.

    Pairing by agent name (not database id) lets a new configuration version be
    compared against its predecessor. Unmatched agents are reported separately
    rather than compared as if they were the same agent.
    """
    policy = policy or {}
    quality_drop = policy.get("max_success_drop", 0.10)
    latency_ratio = policy.get("max_latency_ratio", 1.5)
    cost_ratio = policy.get("max_cost_ratio", 1.5)
    b, c = _aggregate(baseline_cells, agent_names), _aggregate(candidate_cells, agent_names)
    regs = []
    for key in sorted(set(b) & set(c)):
        agent, bid = key
        delta = round(c[key]["success_rate"] - b[key]["success_rate"], 4)
        label = f"{agent} / benchmark {bid}"
        if delta <= -quality_drop:
            regs.append({"benchmark_id": bid, "agent": agent, "type": "quality",
                         "baseline": b[key]["success_rate"], "candidate": c[key]["success_rate"],
                         "delta": delta, "detail": f"{label}: success rate dropped {abs(delta):.1%} (threshold {quality_drop:.0%})"})
    # Aggregate per benchmark and per agent for latency/cost/safety.
    for key in sorted(set(b) & set(c)):
        agent, bid = key
        label = f"{agent} / benchmark {bid}"
        bl, cl = b[key]["latency_p50_ms"], c[key]["latency_p50_ms"]
        if bl and cl and cl > bl * latency_ratio:
            regs.append({"benchmark_id": bid, "agent": agent, "type": "latency",
                         "baseline": bl, "candidate": cl, "delta": round(cl - bl, 2),
                         "detail": f"{label}: p50 latency {bl}ms -> {cl}ms (>{latency_ratio}x)"})
        bc, cc = b[key]["cost"], c[key]["cost"]
        if bc and cc and cc > bc * cost_ratio:
            regs.append({"benchmark_id": bid, "agent": agent, "type": "cost",
                         "baseline": round(bc, 6), "candidate": round(cc, 6),
                         "delta": round(cc - bc, 6),
                         "detail": f"{label}: cost ${bc:.4f} -> ${cc:.4f} (>{cost_ratio}x)"})
        bsec = b[key]["failures"].get("security_violation", 0)
        csec = c[key]["failures"].get("security_violation", 0)
        if csec > bsec:
            regs.append({"benchmark_id": bid, "agent": agent, "type": "safety",
                         "baseline": bsec, "candidate": csec, "delta": csec - bsec,
                         "detail": f"{label}: security violations {bsec} -> {csec} (release blocker)"})
    unmatched_candidate = sorted({k[0] for k in set(c) - set(b)})
    unmatched_baseline = sorted({k[0] for k in set(b) - set(c)})
    return regs, {"matched_cells": len(set(b) & set(c)), "unmatched_candidate_agents": unmatched_candidate,
                  "unmatched_baseline_agents": unmatched_baseline}


def compare_experiments(baseline_summary, candidate_summary, policy=None, agent_names=None):
    regs, coverage = detect_regressions(baseline_summary["cells"], candidate_summary["cells"], policy, agent_names)
    return {"regressions": regs, "coverage": coverage,
            "baseline_overall": baseline_summary["overall"], "candidate_overall": candidate_summary["overall"],
            "methodology": "Matched (agent name, benchmark) cells; Wilson 95% CIs; thresholds from release policy."}


def _binom_two_sided(k, n, p=0.5):
    """Exact two-sided binomial p-value by probability summation."""
    if n == 0:
        return 1.0
    from math import comb
    probs = [comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    pk = probs[k]
    return round(min(1.0, sum(x for x in probs if x <= pk + 1e-12)), 4)


def paired_agent_comparison(trials, agent_a: int, agent_b: int):
    """McNemar exact paired comparison within one experiment."""
    def keyed(aid):
        out = {}
        for t in trials:
            if t.agent_id == aid and t.status in TERMINAL:
                out[(t.benchmark_id, t.repetition)] = bool(t.passed)
        return out

    A, B = keyed(agent_a), keyed(agent_b)
    keys = sorted(set(A) & set(B))
    both = sum(1 for k in keys if A[k] and B[k])
    a_only = sum(1 for k in keys if A[k] and not B[k])
    b_only = sum(1 for k in keys if not A[k] and B[k])
    neither = sum(1 for k in keys if not A[k] and not B[k])
    discordant = a_only + b_only
    p_value = _binom_two_sided(min(a_only, b_only), discordant) if discordant else 1.0
    n = len(keys)
    significant = bool(discordant and p_value < 0.05)
    return {
        "agent_a": agent_a, "agent_b": agent_b, "paired_trials": n,
        "both_pass": both, "a_only_pass": a_only, "b_only_pass": b_only, "both_fail": neither,
        "a_success_rate": round((both + a_only) / n, 4) if n else 0.0,
        "b_success_rate": round((both + b_only) / n, 4) if n else 0.0,
        "mcnemar_exact_p": p_value, "significant_at_0_05": significant,
        "interpretation": (
            "Paired by (benchmark, repetition) within this experiment. "
            + ("Difference is statistically significant at 0.05." if significant
               else "Not significant at 0.05 — do not claim a reliable difference." if discordant
               else "No discordant pairs — agents agreed on every paired trial.")
        ),
    }
