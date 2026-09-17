"""Primary user journey at the API level.

Browser-level screenshots and interaction checks live in frontend/e2e.mjs and
scripts/screenshots.mjs (Playwright/Puppeteer), which run against a real server.
"""
from conftest import create_experiment


def test_primary_journey(client, benchmarks):
    benchmarks = [b for b in benchmarks if b["task_id"] in {
        "repo-repair-v1", "structured-data-v1", "file-artifact-v1",
        "tool-permission-v1", "prompt-injection-v1", "command-safety-v1"}]
    agents = client.get("/api/v1/agents").json()
    ids = [a for a in agents if a["kind"] in ("noop", "rule_based", "scripted_tool")
           and a["version"] == "1.0.0"]
    assert len(ids) == 3
    e = create_experiment(client, "e2e journey", ids, benchmarks, repetitions=1)
    result = client.post(f"/api/v1/experiments/{e['id']}/run").json()
    assert result["status"] == "completed"
    assert result["summary"]["overall"]["trials"] == 18
    # The scripted agent passes all six; the baselines deliberately fail some.
    scripted = next(a for a in ids if a["name"] == "scripted-tool-agent")
    row = next(x for x in result["summary"]["per_agent"] if x["agent_id"] == scripted["id"])
    assert row["successes"] == 6

    trial = result["trials"][0]
    assert client.get(f"/api/v1/trials/{trial['id']}/trajectory").status_code == 200
    assert client.get(f"/api/v1/trials/{trial['id']}/artifacts").status_code == 200

    report = client.post(f"/api/v1/experiments/{e['id']}/report", json={}).json()
    assert report["gate"] in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")
    assert report["summary"]["overall"]["trials"] == 18
