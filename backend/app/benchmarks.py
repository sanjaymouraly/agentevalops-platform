"""Benchmark manifest discovery and validation."""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import yaml

from .config import get_settings

REQUIRED = ["task_id", "version", "name", "verifier"]
SAFE_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


class ManifestError(ValueError):
    pass


def _load_raw(task_dir: Path) -> dict:
    for name in ("task.json", "task.yaml", "task.yml", "task.toml"):
        p = task_dir / name
        if not p.exists():
            continue
        if name.endswith(".json"):
            data = json.loads(p.read_text())
        elif name.endswith(".toml"):
            data = tomllib.loads(p.read_text())
        else:
            data = yaml.safe_load(p.read_text())
        if not isinstance(data, dict):
            raise ManifestError("Manifest must be a mapping")
        return data
    raise ManifestError(f"No task manifest (task.json/yaml/toml) in {task_dir}")


def validate_manifest(data: dict, task_dir: Path | None = None) -> dict:
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise ManifestError(f"Manifest missing fields {missing}")
    task_id = str(data["task_id"])
    if not task_id or any(ch not in SAFE_ID for ch in task_id) or task_id.startswith("."):
        raise ManifestError(f"Unsafe task_id: {task_id!r}")
    if len(task_id) > 120:
        raise ManifestError("task_id is too long")
    data["version"] = str(data["version"])
    data["name"] = str(data["name"])
    data["difficulty"] = str(data.get("difficulty", "medium"))
    if data["difficulty"] not in ("easy", "medium", "hard", "expert"):
        raise ManifestError("difficulty must be easy|medium|hard|expert")
    data["timeout_sec"] = int(data.get("timeout_sec", 60))
    if not 1 <= data["timeout_sec"] <= 3600:
        raise ManifestError("timeout_sec must be between 1 and 3600")
    data["tools"] = list(data.get("tools", ["read_file", "write_file", "list_files"]))
    unknown_tools = set(data["tools"]) - {"read_file", "write_file", "list_files", "run_command"}
    if unknown_tools:
        raise ManifestError(f"Unsupported tools: {sorted(unknown_tools)}")
    data["allowed_commands"] = list(data.get("allowed_commands", ["python3 --version"]))
    data["prohibited_paths"] = [str(p) for p in data.get("prohibited_paths", [])]
    for path in data["prohibited_paths"]:
        if path.startswith("/") or ".." in Path(path).parts:
            raise ManifestError(f"Unsafe prohibited path: {path}")
    limits = data.get("resource_limits") or {}
    data["resource_limits"] = {
        "cpu": float(limits.get("cpu", 1)),
        "memory_mb": int(limits.get("memory_mb", 512)),
        "max_file_bytes": int(limits.get("max_file_bytes", 1_000_000)),
    }
    if data["resource_limits"]["memory_mb"] > 4096:
        raise ManifestError("memory_mb above 4096 is not allowed in local mode")
    hidden = str(data.get("hidden_tests", "") or "")
    if hidden:
        hp = Path(hidden)
        if hp.is_absolute() or ".." in hp.parts or (hp.parts and hp.parts[0] != "private"):
            raise ManifestError("hidden_tests must be a relative path under private/")
    data["hidden_tests"] = hidden
    data["verifier"] = str(data["verifier"])
    from .verifiers import VERIFIERS
    if data["verifier"] not in VERIFIERS:
        raise ManifestError(f"Unknown verifier {data['verifier']!r}; choose from {sorted(VERIFIERS)}")
    if task_dir is not None:
        ws = task_dir / "workspace"
        if ws.exists():
            for p in ws.rglob("*"):
                if p.is_symlink():
                    raise ManifestError(f"Agent-visible workspace may not contain symlinks: {p.relative_to(task_dir)}")
                if p.is_file() and p.stat().st_size > data["resource_limits"]["max_file_bytes"]:
                    raise ManifestError(f"Workspace fixture too large: {p.relative_to(task_dir)}")
        private = task_dir / "private"
        if private.exists() and ws.exists() and any(private in p.parents for p in ws.rglob("*")):
            raise ManifestError("Private data must not be inside agent-visible workspace")
    return data


def load_manifest(task_dir: Path) -> dict:
    data = validate_manifest(_load_raw(task_dir), task_dir)
    instr = task_dir / "instruction.md"
    data["instruction"] = instr.read_text() if instr.exists() else data.get("instruction", "")
    data["_dir"] = str(task_dir)
    return data


def content_hash(task_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(task_dir.rglob("*")):
        if p.is_file() and "private" not in p.parts:
            h.update(str(p.relative_to(task_dir)).encode())
            h.update(p.read_bytes())
    # Hash private verifier material too, without exposing it (provenance).
    for p in sorted(task_dir.rglob("*")):
        if p.is_file() and "private" in p.parts:
            h.update(b"private:")
            h.update(str(p.relative_to(task_dir)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def discover(benchmark_dir: Path | None = None) -> list[dict]:
    root = benchmark_dir or get_settings().benchmark_dir
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if d.is_dir() and any((d / n).exists() for n in ("task.json", "task.yaml", "task.toml")):
            m = load_manifest(d)
            m["content_hash"] = content_hash(d)
            out.append(m)
    return out


def export_manifest(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if not k.startswith("_")}
