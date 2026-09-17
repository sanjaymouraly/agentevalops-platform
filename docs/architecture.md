# Architecture

```mermaid
flowchart LR
  UI[React + Tailwind dashboard] --> API[FastAPI routers]
  API --> DB[(SQLite / PostgreSQL)]
  API --> EX[Execution orchestrator]
  EX --> SUB[Subprocess executor]
  EX --> DOC[Docker executor]
  SUB --> WS[Fresh per-trial workspace]
  DOC --> WS
  WS --> AG[Agent adapters]
  AG --> PROV[Provider abstraction]
  PROV --> OAI[OpenAI / Claude / Gemini / OpenRouter / Azure / custom]
  PROV --> LOCAL[Ollama / vLLM]
  EX --> VER[Independent verifiers]
  VER --> HIDDEN[Hidden tests / deterministic checks]
  API --> ANALYTICS[Analytics + regression]
  API --> REPORTS[JSON / MD / HTML / PDF reports]
  REPORTS --> APPROVAL[Human approval + audit]
```

## Data flow

1. Benchmarks are loaded from immutable on-disk packages and hashed.
2. Experiments create queued trials for every agent × benchmark × repetition.
3. The executor copies a fresh workspace, runs the agent, then runs an independent verifier.
4. Trajectories, evidence, metrics and artifacts are persisted.
5. Analytics compares matched cells and detects regressions.
6. Reports combine evidence and policy gates; approval is a separate auditable action.