def test_viewer_cannot_mutate(client, viewer_headers):
    r = client.post("/api/v1/agents", headers=viewer_headers,
                    json={"name": "evil", "kind": "noop"})
    assert r.status_code == 403
    assert client.get("/api/v1/audit", headers=viewer_headers).status_code == 403


def test_invalid_key_rejected_on_every_route(client):
    assert client.get("/api/v1/benchmarks", headers={"X-API-Key": "wrong-key"}).status_code == 401
    assert client.get("/health", headers={"X-API-Key": "wrong-key"}).status_code == 401


def test_duplicate_benchmark_version_rejected(client, benchmarks, admin_headers):
    b = benchmarks[0]
    r = client.post("/api/v1/benchmarks", headers=admin_headers,
                    json={"task_id": b["task_id"], "version": b["version"], "name": "dup"})
    assert r.status_code == 409


def test_duplicate_agent_version_rejected_and_mock_llm_refused(client, admin_headers):
    dup = client.post("/api/v1/agents", headers=admin_headers, json={
        "name": "scripted-tool-agent", "version": "1.0.0", "kind": "scripted_tool",
    })
    assert dup.status_code == 409
    mock = client.post("/api/v1/agents", headers=admin_headers, json={
        "name": "fake-llm", "version": "1.0.0", "kind": "llm", "provider": "mock",
        "config": {"provider": {"provider_type": "mock", "model": "mock-1"}},
    })
    assert mock.status_code == 422
    raw_secret = client.post("/api/v1/agents", headers=admin_headers, json={
        "name": "leaky", "version": "1.0.0", "kind": "llm", "provider": "openai",
        "config": {"api_key": "sk-should-not-be-stored"},
    })
    assert raw_secret.status_code == 422


def test_benchmark_sync_literal_route_not_shadowed(client, admin_headers):
    r = client.post("/api/v1/benchmarks/sync", headers=admin_headers)
    assert r.status_code == 200
    assert "synced" in r.json()


def test_approver_role_required_for_release_decision(client, scripted_agent, benchmarks):
    from conftest import create_experiment
    e = create_experiment(client, f"role-gate-{__import__('time').time()}", [scripted_agent], benchmarks[:1])
    client.post(f"/api/v1/experiments/{e['id']}/run")
    report = client.post(f"/api/v1/experiments/{e['id']}/report", json={}).json()
    r = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                    headers={"X-API-Key": "dev-operator-key-change-me"},
                    json={"decision": "rejected"})
    assert r.status_code == 403
    ok = client.post(f"/api/v1/reports/{report['report_id']}/approve",
                     headers={"X-API-Key": "dev-approver-key-change-me"},
                     json={"decision": "rejected", "approver": "release-manager"})
    assert ok.status_code == 200 and ok.json()["role"] == "approver"
