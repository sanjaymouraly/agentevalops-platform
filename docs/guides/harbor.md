# Harbor integration guide

AgentEvalOps can export a native benchmark to a Harbor task directory and import a Harbor task back into the native registry. The native engine works without Harbor installed.

- Export: `GET /api/v1/benchmarks/{id}/harbor-export`
- Import: `POST /api/v1/harbor/import` with `{"harbor_task_dir": "/path/to/task"}`
- Status: `GET /api/v1/harbor/status`