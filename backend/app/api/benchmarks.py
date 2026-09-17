import json
import shutil
import tomllib
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models
from ..benchmarks import ManifestError, content_hash, discover, export_manifest, validate_manifest
from ..config import get_settings
from ..database import get_db
from ..harbor_adapter import export_harbor_task
from ..schemas import BenchmarkImportIn, BenchmarkIn
from ..security import require
from ..seed import seed
from ..serializers import benchmark_out
from .deps import audit, get_benchmark_or_404

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])


def _write_package(settings, data: dict, task_id: str, source_dir: Path | None = None) -> Path:
    pkg = settings.resolved(settings.benchmark_dir) / task_id
    if pkg.exists() and source_dir is None:
        raise HTTPException(409, f"Benchmark package directory already exists: {task_id}")
    if source_dir:
        shutil.copytree(source_dir, pkg, dirs_exist_ok=True)
    else:
        (pkg / "workspace").mkdir(parents=True, exist_ok=True)
    (pkg / "task.json").write_text(json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, indent=2))
    (pkg / "instruction.md").write_text(data.get("instruction", ""))
    (pkg / "README.md").write_text(
        f"# {task_id}\n\nImported through AgentEvalOps. Place agent-visible fixtures in `workspace/` and "
        "private verifier material in `private/` (never visible to agents).\n"
    )
    return pkg


@router.get("")
def list_benchmarks(
    response: Response,
    q: str = "",
    category: str = "",
    difficulty: str = "",
    archived: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.Benchmark).filter_by(archived=archived)
    if category:
        query = query.filter_by(category=category)
    if difficulty:
        query = query.filter_by(difficulty=difficulty)
    rows = query.order_by(models.Benchmark.task_id, models.Benchmark.version).all()
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in f"{r.name} {r.task_id} {r.description} {' '.join(json.loads(r.tags or '[]'))}".lower()]
    response.headers["X-Total-Count"] = str(len(rows))
    return [benchmark_out(r) for r in rows[offset:offset + limit]]


@router.get("/{bench_id:int}")
def get_benchmark(bench_id: int, db: Session = Depends(get_db)):
    return benchmark_out(get_benchmark_or_404(db, bench_id))


@router.post("", status_code=201)
def create_benchmark(payload: BenchmarkIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    if db.query(models.Benchmark).filter_by(task_id=payload.task_id, version=payload.version).first():
        raise HTTPException(409, "Benchmark task_id+version already exists (versions are immutable)")
    settings = get_settings()
    data = payload.model_dump()
    validate_manifest(data)
    pkg = _write_package(settings, data, payload.task_id)
    digest = content_hash(pkg)
    b = models.Benchmark(
        task_id=payload.task_id, version=payload.version, name=payload.name,
        description=payload.description, difficulty=payload.difficulty, category=payload.category,
        tags=json.dumps(payload.tags), instruction=payload.instruction,
        manifest=json.dumps(export_manifest(data)), content_hash=digest, source="native",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    audit(db, auth, "benchmark.create", b.task_id, f"version={b.version} hash={digest}")
    return benchmark_out(b)


@router.post("/{bench_id:int}/versions", status_code=201)
def create_version(bench_id: int, payload: BenchmarkIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    parent = get_benchmark_or_404(db, bench_id)
    if payload.task_id != parent.task_id:
        raise HTTPException(422, "A new version must keep the same task_id")
    if payload.version == parent.version:
        raise HTTPException(409, "New version must differ from the parent version")
    if db.query(models.Benchmark).filter_by(task_id=payload.task_id, version=payload.version).first():
        raise HTTPException(409, "Version already exists")
    settings = get_settings()
    src = settings.resolved(settings.benchmark_dir) / parent.task_id
    if not src.exists():
        raise HTTPException(404, "Parent benchmark package is not on disk")
    data = {
        "task_id": payload.task_id, "version": payload.version, "name": payload.name,
        "description": payload.description, "difficulty": payload.difficulty, "category": payload.category,
        "tags": payload.tags, "instruction": payload.instruction, "verifier": payload.verifier,
        "tools": payload.tools, "allowed_commands": payload.allowed_commands,
        "prohibited_paths": payload.prohibited_paths, "timeout_sec": payload.timeout_sec,
        "resource_limits": payload.resource_limits, "hidden_tests": payload.hidden_tests,
    }
    validate_manifest(data)
    # Stage in a sibling directory first to avoid mixing versions.
    staging = settings.resolved(settings.benchmark_dir) / f".staging-{payload.task_id}-{payload.version}"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(src, staging)
    (staging / "task.json").write_text(json.dumps(data, indent=2))
    final = settings.resolved(settings.benchmark_dir) / payload.task_id
    # Keep older versions archived on disk for provenance; the active task dir is latest.
    archive = settings.resolved(settings.benchmark_dir) / ".versions" / parent.task_id / parent.version
    archive.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name not in (".versions",):
            shutil.copytree(item, archive / item.name, dirs_exist_ok=True) if item.is_dir() else shutil.copy2(item, archive / item.name)
    shutil.rmtree(final)
    staging.rename(final)
    digest = content_hash(final)
    b = models.Benchmark(task_id=payload.task_id, version=payload.version, name=payload.name,
                         description=payload.description, difficulty=payload.difficulty, category=payload.category,
                         tags=json.dumps(payload.tags), instruction=payload.instruction,
                         manifest=json.dumps(data), content_hash=digest, source="native")
    db.add(b)
    db.commit()
    db.refresh(b)
    audit(db, auth, "benchmark.version", b.task_id, f"{parent.version}->{b.version} hash={digest}")
    return benchmark_out(b)


@router.get("/{bench_id:int}/versions")
def versions(bench_id: int, db: Session = Depends(get_db)):
    b = get_benchmark_or_404(db, bench_id)
    return [benchmark_out(x) for x in db.query(models.Benchmark).filter_by(task_id=b.task_id).order_by(models.Benchmark.created_at).all()]


@router.get("/{bench_id:int}/export")
def export_benchmark(bench_id: int, db: Session = Depends(get_db)):
    b = get_benchmark_or_404(db, bench_id)
    data = json.loads(b.manifest or "{}")
    data.update({"task_id": b.task_id, "version": b.version, "name": b.name, "instruction": b.instruction,
                 "content_hash": b.content_hash})
    return {"format": "agentevalops.benchmark/v1", "task_id": b.task_id,
            "version": b.version, "content_hash": b.content_hash, "manifest": data}


@router.get("/{bench_id:int}/harbor-export")
def harbor_export(bench_id: int, db: Session = Depends(get_db)):
    b = get_benchmark_or_404(db, bench_id)
    tasks = {m["task_id"]: m for m in discover()}
    m = tasks.get(b.task_id)
    if not m:
        raise HTTPException(404, "Benchmark files not on disk")
    dest = export_harbor_task(m, Path(m["_dir"]), get_settings().resolved(get_settings().harbor_dir))
    return {"harbor_task_dir": str(dest),
            "files": sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())}


@router.post("/{bench_id:int}/archive")
def archive_benchmark(bench_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    b = get_benchmark_or_404(db, bench_id)
    b.archived = True
    db.commit()
    audit(db, auth, "benchmark.archive", b.task_id, b.version)
    return benchmark_out(b)


@router.post("/sync")
def sync_benchmarks(db: Session = Depends(get_db), auth=Depends(require("operator"))):
    try:
        created = seed(db)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    audit(db, auth, "benchmark.sync", "database", json.dumps(created))
    return {"synced": created}


def _parse_manifest(text: str) -> dict:
    try:
        data = json.loads(text)
    except Exception:
        try:
            data = yaml.safe_load(text)
        except Exception:
            try:
                data = tomllib.loads(text)
            except Exception as e:
                raise HTTPException(422, f"Unparseable manifest: {e}")
    if not isinstance(data, dict):
        raise HTTPException(422, "Manifest must be an object")
    return data


@router.post("/import", status_code=201)
def import_benchmark(payload: BenchmarkImportIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    if len(payload.manifest_text) > 1_000_000:
        raise HTTPException(413, "Manifest too large")
    data = _parse_manifest(payload.manifest_text)
    data.setdefault("instruction", "")
    try:
        validate_manifest(data)
    except ManifestError as e:
        raise HTTPException(422, str(e))
    task_id, version = str(data["task_id"]), str(data["version"])
    if db.query(models.Benchmark).filter_by(task_id=task_id, version=version).first():
        raise HTTPException(409, "task_id+version already exists (immutable versions)")
    settings = get_settings()
    pkg = _write_package(settings, data, task_id)
    digest = content_hash(pkg)
    b = models.Benchmark(
        task_id=task_id, version=version, name=str(data["name"]),
        description=str(data.get("description", "")), difficulty=str(data.get("difficulty", "medium")),
        category=str(data.get("category", "general")), tags=json.dumps(data.get("tags", [])),
        instruction=str(data.get("instruction", "")), manifest=json.dumps(export_manifest(data)), content_hash=digest,
        source="import",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    audit(db, auth, "benchmark.import", b.task_id, f"version={b.version}")
    return {**benchmark_out(b), "warning": "Add workspace fixtures and private hidden tests before trusting scores."}
