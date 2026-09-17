"""Idempotent seed data: benchmarks on disk, local baseline agents, providers."""
import json

from . import models
from .benchmarks import discover
from .config import get_settings
from .database import SessionLocal, init_db

DEFAULT_AGENTS = [
    {
        "name": "noop-baseline", "kind": "noop", "version": "1.0.0", "provider": "offline", "model": "none",
        "description": "No-op baseline: inspects files, takes no action. Establishes the floor.",
    },
    {
        "name": "rule-based-baseline", "kind": "rule_based", "version": "1.0.0", "provider": "offline", "model": "none",
        "description": "Deterministic rule solver. Naive on untrusted content (fails injection/command-safety by design).",
    },
    {
        "name": "scripted-tool-agent", "kind": "scripted_tool", "version": "1.0.0", "provider": "offline", "model": "none",
        "description": "Scripted tool-using agent: scoped reads, ACTION:-only extraction, allowlisted commands.",
    },
    {
        "name": "scripted-tool-agent", "kind": "scripted_tool", "version": "1.1.0-degraded", "provider": "offline", "model": "none",
        "config": {"degraded": True},
        "description": "Deliberately degraded configuration used to demonstrate regression gates. Not a recommended agent.",
    },
    {
        "name": "llm-agent-ollama", "kind": "llm", "version": "1.0.0", "provider": "ollama", "model": "gemma:2b",
        "config": {"max_steps": 3, "max_tokens_budget": 30000,
                   "provider": {"provider_type": "ollama", "base_url": "http://localhost:11434/v1",
                                "model": "gemma:2b", "api_key_env": "", "params": {"temperature": 0.0}}},
        "tools": ["list_files", "read_file", "write_file"],
        "description": "REAL local LLM adapter (Ollama gemma:2b). Fails honestly if Ollama/model is unavailable; not a deterministic baseline.",
    },
]


def seed(db=None):
    init_db()
    settings = get_settings()
    own = db is None
    db = db or SessionLocal()
    try:
        created = {"benchmarks": 0, "agents": 0, "providers": 0, "skipped": 0}
        for m in discover():
            row = db.query(models.Benchmark).filter_by(task_id=m["task_id"], version=m["version"]).first()
            if row:
                if row.content_hash != m["content_hash"]:
                    # Immutable versions: refuse to silently mutate evidence provenance.
                    raise RuntimeError(
                        f"Benchmark {m['task_id']}@{m['version']} changed on disk but the database "
                        "already contains that immutable version. Bump the version or reset the demo DB."
                    )
                created["skipped"] += 1
                continue
            db.add(models.Benchmark(
                task_id=m["task_id"], version=m["version"], name=m["name"],
                description=m.get("description", ""), difficulty=m.get("difficulty", "medium"),
                category=m.get("category", "general"), tags=json.dumps(m.get("tags", [])),
                instruction=m.get("instruction", ""),
                manifest=json.dumps({k: v for k, v in m.items() if k != "_dir"}),
                content_hash=m["content_hash"], source="native",
            ))
            created["benchmarks"] += 1
        for a in DEFAULT_AGENTS:
            if not db.query(models.Agent).filter_by(name=a["name"], version=a["version"]).first():
                db.add(models.Agent(
                    name=a["name"], kind=a["kind"], version=a["version"], provider=a["provider"],
                    model=a["model"], config=json.dumps(a.get("config", {})),
                    tools=json.dumps(a.get("tools", [])), description=a["description"],
                ))
                created["agents"] += 1
        if not db.query(models.ProviderConfig).filter_by(name="offline-mock").first():
            db.add(models.ProviderConfig(name="offline-mock", provider_type="mock", model="mock-1",
                                         is_default=True, params=json.dumps({"note": "No API key required"})))
            created["providers"] += 1
        if not db.query(models.ProviderConfig).filter_by(name="ollama-local").first():
            db.add(models.ProviderConfig(
                name="ollama-local", provider_type="ollama", base_url=settings.ollama_base_url,
                model="gemma:2b", params=json.dumps({"note": "Local runtime; no API charge", "temperature": 0.0}),
            ))
            created["providers"] += 1
        db.add(models.AuditLog(actor="system", role="admin", action="seed", resource="database",
                               detail=json.dumps(created)))
        db.commit()
        return created
    finally:
        if own:
            db.close()


def main():
    print(seed())


if __name__ == "__main__":
    main()
