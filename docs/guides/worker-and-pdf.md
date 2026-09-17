# Worker, PDF reports, reviewer correction
- **Queued worker (no Redis required locally):** `PYTHONPATH=backend python3 -m app.worker_runner --once`
  processes every experiment with queued trials; `--poll 5` loops. `GET /api/v1/worker/status`
  shows queue depth. Docker Compose: `docker compose --profile queued up` adds the same worker
  against PostgreSQL. Production can front the identical `run_experiment` contract with Redis/RQ/Celery.
- **PDF reports:** every generated report now includes `report.pdf` (dependency-free printable PDF);
  download via `GET /api/v1/reports/{id}/download?fmt=pdf` or the PDF button on Release & Approvals.
- **Reviewer correction:** `PATCH /api/v1/trials/{id}/classification` with a taxonomy value sets
  `classification_source=reviewer`, records the reviewer, and writes an audit entry. The dashboard
  exposes this in the trial trace panel. Rule-based classification remains the default provenance.
- **Retention:** `POST /api/v1/admin/cleanup` (admin, `dry_run=true` by default) removes artifact
  directories older than N days while retaining DB evidence rows.
- **Benchmark import/export:** `GET /api/v1/benchmarks/{id}/export`, `POST /api/v1/benchmarks/import`
  (JSON/YAML manifest, validated, immutable versions; materializes an on-disk task package).
- **Harbor import:** `POST /api/v1/harbor/import {"harbor_task_dir": "..."}`; reward parsing follows
  Harbor's documented precedence (`reward.txt` over `reward.json`).
