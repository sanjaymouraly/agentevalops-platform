# Execution Modes & Isolation
Set `AGENTEVALOPS_EXECUTION_MODE`:
- `local` (default): agent runs in-process through the jailed ToolContext (fresh workspace,
  prohibited prefixes, redaction). Fast; appropriate for trusted deterministic baselines.
- `subprocess`: the agent runs in a child process (`app.trial_worker`) with a **hard timeout**
  (`subprocess.run(timeout=...)` kills the process — verified by a sleeper-agent test that is
  killed at 2s), OS limits (CPU time, 2 GiB address space, process count), a scrubbed
  environment (no host secrets; a provider key is forwarded only by env-var name for LLM
  agents), and trajectory JSON passed back across the process boundary. Verifiers still run
  in the parent. Recommended whenever an agent is not fully trusted locally.
- Docker: `app.sandbox.build_docker_command` encodes the restricted policy (network none,
  cap-drop ALL, read-only rootfs, non-root, limits). Container lifecycle belongs to the
  separated privileged worker; Docker is defence-in-depth, **not** a hostile multi-tenant
  boundary (see SECURITY.md). A microVM/gVisor worker remains the hardened future interface.

# PostgreSQL (verified 2026-10-19)
PostgreSQL 17 + psycopg: the full test suite (37 tests) and two consecutive 54-trial
acceptance runs pass with identical results (30/54) using
`AGENTEVALOPS_DATABASE_URL=postgresql+psycopg://agentevalops:***@localhost:5432/agentevalops`.
Alembic `upgrade head` verified on both SQLite and PostgreSQL.
This run exposed (and fixed) a verifier race: `verify_repo_repair` previously shared
`sys.modules`/`sys.path` across concurrent trials; it now loads the module under a
workspace-unique name, with a concurrency regression test.

# Harbor CLI (verified 2026-10-19)
Harbor 0.24.0 (isolated venv): `harbor --help` executes successfully through
`app.harbor_adapter.run_harbor_job`. `harbor check` on an exported task proceeds until it
requires a Docker daemon (`FileNotFoundError: 'docker'`) — Harbor *execution* therefore
remains blocked only by the absence of Docker in this sandbox, not by the adapter.
