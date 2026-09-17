# Security Policy

AgentEvalOps is an evaluation harness, not a multi-tenant sandbox. Please read
this before exposing it beyond localhost.

## Supported isolation modes

- `AGENTEVALOPS_EXECUTION_MODE=local` runs agents in the API process. Use only for trusted deterministic baselines.
- `subprocess` (default) gives each trial a fresh workspace, sanitized environment, hard timeout, process-group kill and POSIX resource limits.
- `docker` adds container isolation with a read-only root filesystem, no capabilities, no Docker socket, memory and CPU limits, and configurable network.

None of these modes makes arbitrary hostile code safe for untrusted multi-tenant execution. For that, run the same executor contract behind a microVM (Firecracker/gVisor) worker.

## Secret handling

- Provider API keys are read from server environment variables only. The database stores a masked hint (`api_key_masked`) and the environment variable name (`api_key_env`).
- Raw keys sent to `/api/v1/providers` or `/api/v1/providers/test` are used for that request only and are redacted from logs and audit records.
- Agent configuration rejects fields named `api_key`, `secret`, `password`, etc.
- The mock provider is wiring/test infrastructure only and cannot be registered as an LLM agent.

## Authentication and RBAC

- Roles: `viewer`, `operator`, `approver`, `admin`. Keys are compared with `hmac.compare_digest`.
- `AGENTEVALOPS_ALLOW_ANONYMOUS=true` (default) grants admin access without a key for local development. Set it to `false` before any network exposure and provide unique keys.
- A client cannot escalate by claiming a role; only a matching server key grants it.

## Synthetic data only

- Security benchmarks contain synthetic secrets (`SYNTHETIC_SECRET_*`). No real credentials are used or should be added.
- Verifiers check outputs and successful prohibited reads, not agent self-report.
- Blocked permission attempts are evidence and risk signals, not successful breaches.

## Reporting vulnerabilities

Please open a private security advisory on the GitHub repository or email the maintainer. Do not file public issues for undisclosed vulnerabilities. Include reproduction steps and affected versions.

## Known limitations

- Docker isolation is defence-in-depth, not a hostile multi-tenant guarantee.
- Costs are unknown unless per-million-token pricing is configured.
- PASS is qualification evidence only; it is not a production deployment authorization.