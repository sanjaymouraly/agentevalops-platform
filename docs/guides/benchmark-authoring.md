# Benchmark authoring guide

1. Create a directory under `benchmarks/examples/<task-id>/`.
2. Add `task.json` with `task_id`, `version`, `name`, `verifier`, and optional fields.
3. Add `instruction.md`, `workspace/` fixtures, and `private/` hidden tests.
4. Validate with `PYTHONPATH=backend python -c "from app.benchmarks import discover; print(discover())"`.
5. Bump `version` when changing an existing immutable task.
6. Hidden tests must live under `private/` and never be copied into `workspace/`.