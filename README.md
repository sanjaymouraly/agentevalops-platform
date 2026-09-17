# AgentEvalOps — Continuous AI Agent Qualification Platform

A continuous qualification platform for evaluating AI agents across benchmarks and production signals.

## Features

- Versioned, immutable benchmarks with content hashes and hidden pytest suites.
- Three deterministic local agents (noop, rule-based, scripted-tool) plus a real multi-step LLM adapter.
- Provider support: OpenAI, Anthropic Claude, OpenRouter, Google Gemini, Azure OpenAI, Ollama, vLLM, custom OpenAI-compatible endpoints, and a clearly labelled mock for wiring tests.
- Isolated execution: fresh workspace per trial, subprocess (default) or Docker, hard timeout and process-group kill.
- Independent deterministic verifiers; hidden tests are never visible to agents.
- Failure taxonomy with rule, confidence and reviewer corrections.
- Statistics: Wilson confidence intervals, unbiased pass@k, exact McNemar, regression detection.

## Stack

Python, Node.js, FastAPI, Uvicorn, SQLAlchemy, Pydantic, HTTPX, PyYAML, pytest, React

## Clone

```bash
git clone https://github.com/sanjaymouraly/agentevalops-platform.git
cd agentevalops-platform
```

## Setup

```bash
# The project ships a Docker Compose setup.
docker compose up --build
```

See `docs/` or the compose file for environment variables and ports.

## Run

```bash
docker compose up --build
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2026 [Sanjay Mouraly](https://github.com/sanjaymouraly)
