"""Deterministic failure classification from evidence.

Every category is attached to a rule and a confidence. The platform never
asserts a root cause that the evidence cannot support: unsupported cases become
``unclassified`` and infrastructure/provider failures are not counted as agent
incompetence.
"""
from __future__ import annotations

FAILURE_TAXONOMY = [
    "none", "incorrect_solution", "assertion_failure", "tool_failure",
    "invalid_tool_arguments", "reasoning_failure", "security_violation",
    "timeout", "resource_exhaustion", "budget_exhaustion", "provider_failure",
    "infrastructure_failure", "nondeterminism", "unclassified",
]


def classify_detailed(status, verifier_result, ctx, exc=None) -> dict:
    """Return ``{category, detail, confidence, rule}``."""
    if status == "timed_out":
        return {"category": "timeout", "detail": "Trial exceeded its timeout budget", "confidence": 1.0, "rule": "status.timeout"}
    if status == "cancelled":
        return {"category": "unclassified", "detail": "Trial was cancelled by an operator", "confidence": 1.0, "rule": "status.cancelled"}
    if status == "budget_exhausted":
        return {"category": "budget_exhaustion", "detail": "Token or cost budget exhausted", "confidence": 0.95, "rule": "status.budget"}

    if exc is not None:
        msg = str(exc)
        low = msg.lower()
        provider_markers = ("provider", "api key", "auth_error", "rate limit", "rate_limit", "401", "429", "connection", "no api key")
        if any(marker in low for marker in provider_markers):
            return {"category": "provider_failure", "detail": msg[:500], "confidence": 0.9, "rule": "exception.provider"}
        if isinstance(exc, (MemoryError,)) or "resource" in low or "too large" in low:
            return {"category": "resource_exhaustion", "detail": msg[:500], "confidence": 0.85, "rule": "exception.resource"}
        return {"category": "infrastructure_failure", "detail": msg[:500], "confidence": 0.8, "rule": "exception.infrastructure"}

    if verifier_result is None:
        return {"category": "infrastructure_failure", "detail": "Verifier produced no result", "confidence": 0.9, "rule": "verifier.missing"}

    checks = verifier_result.get("checks") or {}
    passed = verifier_result.get("passed")
    if passed:
        return {"category": "none", "detail": "", "confidence": 1.0, "rule": "verifier.pass"}

    category = verifier_result.get("failure_category", "assertion_failure")
    detail = verifier_result.get("evidence", "")
    confidence = 0.9
    rule = f"verifier.{category}"

    if category == "security_violation" or (ctx and ctx.permission_attempts and category == "security_violation"):
        confidence = 0.98
        if ctx and ctx.permission_attempts:
            detail += f" | blocked permission attempts: {ctx.permission_attempts[:5]}"
    elif category == "incorrect_solution":
        # Distinguish "nothing was produced" from "produced but wrong".
        exists = checks.get("output_exists", checks.get("import", True))
        if exists is False:
            detail = (detail + " | required output/artifact was not produced").strip(" |")
            rule = "verifier.missing_output"
            confidence = 0.9
        else:
            rule = "verifier.mismatch"
            confidence = 0.92
    elif category == "assertion_failure":
        confidence = 0.85
    else:
        confidence = 0.7

    if not category or category not in FAILURE_TAXONOMY:
        category = "unclassified"
        confidence = 0.5
    return {"category": category, "detail": detail, "confidence": confidence, "rule": rule,
            "checks": {k: bool(v) for k, v in checks.items()}}


def classify(status, verifier_result, ctx, exc=None):
    """Backward-compatible ``(category, detail)`` helper."""
    info = classify_detailed(status, verifier_result, ctx, exc)
    return info["category"], info["detail"]
