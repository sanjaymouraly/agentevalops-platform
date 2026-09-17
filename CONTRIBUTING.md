# Contributing

1. Fork and create a feature branch.
2. Set up locally (see README).
3. Run the test suite before submitting:
   ```bash
   PYTHONPATH=backend .venv/bin/python -m pytest tests -q
   (cd frontend && npm run build)
   ```
4. Keep changes focused and add tests for new behaviour.
5. Never commit API keys, `.env`, local databases, artifacts, or generated reports.
6. Security-sensitive changes (sandbox, RBAC, secret handling) require review and updated SECURITY.md.

## Development notes

- Backend dependencies: `requirements.txt` plus `requirements-dev.txt`.
- Frontend: React + TypeScript + Vite + Tailwind.
- Benchmarks are immutable versions: change a task and bump its version rather than mutating a released one.
- Hidden tests live under `benchmarks/.../private/` and are never copied into agent-visible workspaces.