"""Local RBAC, secret redaction, and API key policy.

Keys are compared with :func:`hmac.compare_digest`. The default development
configuration permits keyless access so a fresh checkout is usable offline;
set ``AGENTEVALOPS_ALLOW_ANONYMOUS=false`` before exposing the API.
"""
import hmac
import re

from fastapi import Header, HTTPException

from .config import get_settings

SECRET_PATTERNS = [
    (re.compile(r"(sk-[A-Za-z0-9_-]{8,})"), "sk-***REDACTED***"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{12,}"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(password\s*[:=]\s*)\S+"), r"\1***REDACTED***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***REDACTED***"),
    (re.compile(r"SYNTHETIC_SECRET_[A-Z0-9_]+"), "SYNTHETIC_SECRET_REDACTED"),
]


def redact(text: str) -> str:
    out = str(text)
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def mask_key(key: str) -> str:
    if not key:
        return ""
    return ("*" * max(0, len(key) - 4)) + key[-4:] if len(key) > 8 else "****"


ROLES = {"viewer": 1, "operator": 2, "approver": 3, "admin": 4}


def _match(value: str | None, expected: str) -> bool:
    return bool(value) and hmac.compare_digest(str(value), str(expected))


def resolve_role(x_api_key: str | None) -> tuple[str, str]:
    """Return ``(actor, role)`` or raise 401/403.

    There is deliberately no client-supplied role header: a caller cannot
    escalate by claiming a role, only by presenting a matching server key.
    """
    s = get_settings()
    if _match(x_api_key, s.admin_key):
        return ("local-admin", "admin")
    if _match(x_api_key, s.approver_key):
        return ("local-approver", "approver")
    if _match(x_api_key, s.operator_key):
        return ("local-operator", "operator")
    if _match(x_api_key, s.viewer_key):
        return ("local-viewer", "viewer")
    if not x_api_key:
        if s.allow_anonymous:
            return ("local-admin", "admin")
        raise HTTPException(401, "API key required (set AGENTEVALOPS_ALLOW_ANONYMOUS=false disables keyless dev access)")
    raise HTTPException(401, "Invalid API key")


def require(min_role: str):
    def dep(x_api_key: str | None = Header(default=None)):
        actor, role = resolve_role(x_api_key)
        if ROLES[role] < ROLES[min_role]:
            raise HTTPException(403, f"Role '{role}' requires '{min_role}'")
        return actor, role

    return dep


def can(role: str, min_role: str) -> bool:
    return ROLES.get(role, 0) >= ROLES[min_role]
