# Architecture

```mermaid
flowchart LR
  UI[React Dashboard] --> API[FastAPI API + RBAC + Audit]
  API --> DB[(SQLite dev / PostgreSQL prod)]
  API --> EX[Execution Engine]
  EX --> TL[Tool Layer: path jail, prohibited prefixes, redaction]
  TL --> AG[Agents: noop / rule / scripted / LLM adapter]
  EX --> VF[Deterministic Verifiers]
  EX --> ART[(Artifacts: trajectories, workspaces, reports)]
  VF --> AN[Analytics: Wilson CI, pass@k, regressions]
  AN --> RP[Release Reports MD/HTML/JSON]
  RP --> HU{Human Approval<br/>approver/admin only}
  API --> PV[Providers: mock / OpenAI / Anthropic / Gemini / OpenRouter / Ollama / vLLM / custom]
  API --> HB[Harbor adapter: task.toml import/export, reward parsing]
```

Package layout is a single Python package (`backend/app`) with separated modules
(config, database, models, security, benchmarks, tools, agents, providers, verifiers,
execution, classification, analytics, reports, harbor_adapter, sandbox) — the top-level
`agents/ providers/ evaluation/ sandbox/ analytics/ worker/ reports/` folders document the
extension points without duplicating implementations.

## Data flow (primary journey)
Create/select task → configure agents/providers → create experiment (trials queued) →
run (fresh workspace per trial, tool-layer trajectory) → independent verifier →
failure classification → analytics (success rate, CI, pass@k, latency, failures) →
comparison/regression vs baseline → release report + gate → human approve/reject (audited).

## Execution states
queued → preparing/copying workspace → running → verifying → completed | failed | timed_out | cancelled.
Infrastructure/provider failures are classified separately and never silently counted as agent incompetence.
