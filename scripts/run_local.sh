#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
(cd frontend && npm install && npm run build)
PYTHONPATH=backend python3 -m app.seed
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000 &
echo "API+UI: http://localhost:8000  (UI is served from frontend/dist when built)"
wait
