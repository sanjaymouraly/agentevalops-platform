import shutil
import time
from pathlib import Path

from app.config import get_settings
from app.database import SessionLocal
from app.worker_runner import pending_experiment_ids, run_once
from conftest import create_experiment


def test_benchmark_import_export_versioning_and_validation(client, admin_headers):
    bad = client.post("/api/v1/benchmarks/import", json={"manifest_text": '{"task_id": "x"}'},
                      headers=admin_headers)
    assert bad.status_code == 422
    uniq = f"imported-{int(time.time() * 1000)}"
    manifest = (f'{{"task_id":"{uniq}","version":"1.0.0","name":"Imported","verifier":"repo_repair",'
                f'"instruction":"do it"}}')
    created = client.post("/api/v1/benchmarks/import", json={"manifest_text": manifest},
                          headers=admin_headers)
    assert created.status_code == 201, created.text
    bench = created.json()
    assert client.get(f"/api/v1/benchmarks/{bench['id']}/export").json()["task_id"] == uniq
    duplicate = client.post("/api/v1/benchmarks/import", json={"manifest_text": manifest},
                            headers=admin_headers)
    assert duplicate.status_code == 409
    version = client.post(f"/api/v1/benchmarks/{bench['id']}/versions", headers=admin_headers, json={
        "task_id": uniq, "version": "1.1.0", "name": "Imported v1.1",
        "verifier": "repo_repair", "instruction": "do it better",
    })
    assert version.status_code == 201, version.text
    assert version.json()["version"] == "1.1.0"
    versions = client.get(f"/api/v1/benchmarks/{bench['id']}/versions").json()
    assert {v["version"] for v in versions} == {"1.0.0", "1.1.0"}
    for row in versions:
        client.post(f"/api/v1/benchmarks/{row['id']}/archive", headers=admin_headers)
    shutil.rmtree(Path(get_settings().benchmark_dir) / uniq, ignore_errors=True)


def test_trial_classification_correction_is_audited(client, scripted_agent, benchmarks, admin_headers):
    e = create_experiment(client, f"correction-{time.time()}", [scripted_agent], benchmarks[:1])
    client.post(f"/api/v1/experiments/{e['id']}/run")
    trial = client.get(f"/api/v1/experiments/{e['id']}").json()["trials"][0]
    bad = client.patch(f"/api/v1/trials/{trial['id']}/classification",
                       json={"failure_category": "not-a-category"}, headers=admin_headers)
    assert bad.status_code == 422
    ok = client.patch(f"/api/v1/trials/{trial['id']}/classification", headers=admin_headers,
                      json={"failure_category": "unclassified", "reviewer": "pytest-reviewer",
                            "notes": "manual review"})
    assert ok.status_code == 200
    assert ok.json()["classification_source"] == "reviewer"
    assert ok.json()["classification_confidence"] == 1.0
    audit = client.get("/api/v1/audit").json()
    assert any(a["action"] == "trial.classification_correct" for a in audit)
    assert "pytest-reviewer" in str(audit)


def test_worker_status_and_cleanup_dry_run(client, admin_headers):
    status = client.get("/api/v1/worker/status").json()
    assert "trial_status_counts" in status and "queue_depth" in status
    cleanup = client.post("/api/v1/admin/cleanup", headers=admin_headers,
                          json={"older_than_days": 3650, "dry_run": True})
    assert cleanup.status_code == 200
    assert cleanup.json()["dry_run"] is True and cleanup.json()["removed"] == []


def test_worker_runner_processes_queued_experiment(client, benchmarks):
    noop = next(a for a in client.get("/api/v1/agents").json() if a["name"] == "noop-baseline")
    e = create_experiment(client, f"worker-{time.time()}", [noop], benchmarks[:1])
    db = SessionLocal()
    try:
        assert e["id"] in pending_experiment_ids(db)
        done = run_once(db)
        assert e["id"] in done
        assert e["id"] not in pending_experiment_ids(db)
    finally:
        db.close()
    after = client.get(f"/api/v1/experiments/{e['id']}").json()
    assert after["status"] == "completed"
    assert after["summary"]["overall"]["trials"] == 1
    assert after["summary"]["overall"]["successes"] == 0


def test_reproducibility_across_repeated_experiments(client, scripted_agent, benchmarks):
    picks = [b for b in benchmarks if b["task_id"] in
             {"repo-repair-v1", "structured-data-v1", "file-artifact-v1"}]
    outcomes = []
    for i in range(2):
        e = create_experiment(client, f"repro-{i}-{time.time()}", [scripted_agent], picks)
        r = client.post(f"/api/v1/experiments/{e['id']}/run").json()
        outcomes.append((r["summary"]["overall"]["successes"], r["summary"]["overall"]["trials"]))
    assert outcomes[0] == outcomes[1] == (3, 3)


def test_regression_comparison_and_agent_compare(client, scripted_agent, degraded_agent, benchmarks):
    benchmarks = [b for b in benchmarks if b["task_id"] in {
        "repo-repair-v1", "structured-data-v1", "file-artifact-v1",
        "tool-permission-v1", "prompt-injection-v1", "command-safety-v1"}]
    baseline = create_experiment(client, f"baseline-{time.time()}", [scripted_agent], benchmarks)
    b = client.post(f"/api/v1/experiments/{baseline['id']}/run").json()
    assert b["summary"]["overall"]["successes"] == 6

    candidate = create_experiment(client, f"candidate-{time.time()}", [degraded_agent], benchmarks,
                                  baseline=baseline["id"])
    c = client.post(f"/api/v1/experiments/{candidate['id']}/run").json()
    assert c["summary"]["overall"]["successes"] < 6

    comparison = client.get(f"/api/v1/experiments/{candidate['id']}/compare").json()
    assert comparison["coverage"]["matched_cells"] == 6
    types = {r["type"] for r in comparison["regressions"]}
    assert "quality" in types and "safety" in types

    both = create_experiment(client, f"paired-{time.time()}", [scripted_agent, degraded_agent],
                             [b for b in benchmarks if b["category"] == "security"])
    client.post(f"/api/v1/experiments/{both['id']}/run")
    paired = client.get(f"/api/v1/experiments/{both['id']}/agent-compare",
                        params={"a": scripted_agent["id"], "b": degraded_agent["id"]}).json()
    assert paired["paired_trials"] == 3
    assert paired["a_success_rate"] >= paired["b_success_rate"]
    assert "mcnemar_exact_p" in paired


def test_analytics_endpoints(client, benchmarks):
    overview = client.get("/api/v1/analytics/overview").json()
    assert overview["summary"]["overall"]["trials"] > 0
    failures = client.get("/api/v1/analytics/failures").json()
    assert "distribution" in failures and "taxonomy" in failures
    security = client.get("/api/v1/analytics/security").json()
    assert security["security_trials"] > 0
    costs = client.get("/api/v1/analytics/costs").json()
    assert "known_cost_usd" in costs and "trials_with_unknown_cost" in costs
