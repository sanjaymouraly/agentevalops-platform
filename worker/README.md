# Worker
Local mode runs trials in a ThreadPoolExecutor inside the API process (`backend/app/execution.py`).
Production queued mode: set `AGENTEVALOPS_EXECUTION_MODE` and front the same `run_experiment` service with
Redis/RQ or Celery — the executor contract (`run_trial(db, trial)`) is queue-agnostic by design.
The privileged container-management worker must stay separated from the web API (see SECURITY.md).
