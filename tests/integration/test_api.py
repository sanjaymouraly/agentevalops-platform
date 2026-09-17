import time

from conftest import create_experiment


def test_health_ready_and_seed_data(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["benchmarks_in_db"] >= 6
    assert ready["execution_mode"] == "subprocess"
    assert len(client.get("/api/v1/benchmarks").json()) >= 6
    kinds = {a["kind"] for a in client.get("/api/v1/agents").json()}
    assert {"noop", "rule_based", "scripted_tool"} <= kinds
    assert client.get("/api/v1/meta").json()["role"] == "admin"


def test_full_workflow_report_and_approval_gate(client, scripted_agent, benchmarks, admin_headers, viewer_headers):
    e = create_experiment(client, f"workflow-{time.time()}", [scripted_agent], benchmarks)
    r = client.post(f"/api/v1/experiments/{e['id']}/run").json()
    assert r["status"] == "completed"
    assert r["summary"]["overall"]["trials"] == 6
    assert r["summary"]["overall"]["successes"] == 6
    assert all(t["config_snapshot"]["content_hash"] for t in r["trials"])

    report = client.post(f"/api/v1/experiments/{e['id']}/report", json={}).json()
    assert report["gate"] in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")
    assert report["report_id"]

    denied = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                         json={"decision": "approved", "approver": "viewer"},
                         headers=viewer_headers)
    assert denied.status_code == 403

    no_override = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                              json={"decision": "approved", "approver": "operator"},
                              headers=admin_headers)
    if report["gate"] == "PASS":
        assert no_override.status_code == 200
    else:
        assert no_override.status_code == 409
        missing_just = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                                   json={"decision": "approved", "override_gate": True,
                                         "approver": "operator"}, headers=admin_headers)
        assert missing_just.status_code == 422
        ok = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                         json={"decision": "approved", "override_gate": True,
                               "justification": "accepted risk for demo", "approver": "operator"},
                         headers=admin_headers)
        assert ok.status_code == 200 and ok.json()["override_gate"] is True

    rejected = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                           json={"decision": "rejected", "approver": "qa-lead", "notes": "needs more trials"},
                           headers=admin_headers)
    assert rejected.status_code == 200 and rejected.json()["decision"] == "rejected"
    assert any(a["action"].startswith("report.") for a in client.get("/api/v1/audit").json())


def test_report_downloads_and_pdf(client, scripted_agent, benchmarks):
    e = create_experiment(client, f"downloads-{time.time()}", [scripted_agent], benchmarks[:1])
    client.post(f"/api/v1/experiments/{e['id']}/run")
    report = client.post(f"/api/v1/experiments/{e['id']}/report", json={}).json()
    for fmt in ("markdown", "html", "json", "pdf"):
        response = client.get(f"/api/v1/reports/{report['report_id']}/download?fmt={fmt}")
        assert response.status_code == 200 and len(response.content) > 100
    pdf = client.get(f"/api/v1/reports/{report['report_id']}/download?fmt=pdf")
    assert pdf.content.startswith(b"%PDF")
    history = client.get(f"/api/v1/reports?experiment_id={e['id']}").json()
    assert any(row["id"] == report["report_id"] for row in history)


def test_provider_secret_is_never_persisted(client, admin_headers):
    name = f"pytest-mock-{int(time.time() * 1000)}"
    p = client.post("/api/v1/providers", headers=admin_headers, json={
        "name": name, "provider_type": "mock", "model": "mock-1",
        "api_key": "sk-secretvalue123",
    }).json()
    assert "sk-secretvalue123" not in str(p)
    assert p["api_key_masked"].endswith("e123")
    listing = client.get("/api/v1/providers").json()
    assert "sk-secretvalue123" not in str(listing)
    assert client.post("/api/v1/providers/test", json={
        "provider_type": "mock", "api_key": "sk-transient-only",
    }).json()["ok"] is True
    assert "sk-transient-only" not in str(client.get("/api/v1/audit").json())
    client.delete(f"/api/v1/providers/{p['id']}", headers=admin_headers)


def test_harbor_status_and_export(client, benchmarks):
    status = client.get("/api/v1/harbor/status").json()
    assert "available" in status
    repo = next(b for b in benchmarks if b["task_id"] == "repo-repair-v1")
    exported = client.get(f"/api/v1/benchmarks/{repo['id']}/harbor-export").json()
    assert "task.toml" in exported["files"]
    assert any("verifier/run.py" in f for f in exported["files"])
    assert any("private/test_calc.py" in f for f in exported["files"])
