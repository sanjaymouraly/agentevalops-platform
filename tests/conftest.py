"""Shared test fixtures.

Every test run uses an isolated SQLite database, artifact directory and
benchmark copy. The repository's development database and example packages are
never mutated by tests.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="agentevalops-tests-"))
BENCH = TMP / "benchmarks"
shutil.copytree(ROOT / "benchmarks" / "examples", BENCH)

os.environ["AGENTEVALOPS_DATABASE_URL"] = f"sqlite:///{TMP / 'test.db'}"
os.environ["AGENTEVALOPS_ARTIFACT_DIR"] = str(TMP / "artifacts")
os.environ["AGENTEVALOPS_BENCHMARK_DIR"] = str(BENCH)
os.environ["AGENTEVALOPS_HARBOR_DIR"] = str(TMP / "harbor")
os.environ["AGENTEVALOPS_ENVIRONMENT"] = "test"
os.environ["AGENTEVALOPS_ALLOW_ANONYMOUS"] = "true"
os.environ["AGENTEVALOPS_EXECUTION_MODE"] = "subprocess"
os.environ["AGENTEVALOPS_MAX_CONCURRENCY"] = "4"
os.environ["AGENTEVALOPS_TRIAL_TIMEOUT_SEC"] = "60"

sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture(scope="session")
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def bench_dir() -> Path:
    return BENCH


@pytest.fixture(scope="session")
def admin_headers():
    return {"X-API-Key": "dev-admin-key-change-me"}


@pytest.fixture(scope="session")
def viewer_headers():
    return {"X-API-Key": "dev-viewer-key-change-me"}


@pytest.fixture()
def scripted_agent(client):
    rows = client.get("/api/v1/agents").json()
    return next(a for a in rows if a["name"] == "scripted-tool-agent" and a["version"] == "1.0.0")


@pytest.fixture()
def degraded_agent(client):
    rows = client.get("/api/v1/agents").json()
    return next(a for a in rows if a["name"] == "scripted-tool-agent" and a["version"] == "1.1.0-degraded")


@pytest.fixture()
def benchmarks(client):
    return sorted(client.get("/api/v1/benchmarks").json(), key=lambda b: b["task_id"])


def create_experiment(client, name, agents, benches, repetitions=1, baseline=None, policy=None):
    payload = {
        "name": name,
        "agent_ids": [a["id"] for a in agents],
        "benchmark_ids": [b["id"] for b in benches],
        "repetitions": repetitions,
        "baseline_experiment_id": baseline,
        "policy": policy or {},
    }
    response = client.post("/api/v1/experiments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()
