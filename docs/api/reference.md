# API Reference
Interactive OpenAPI: `http://localhost:8000/docs` (schema at `/openapi.json`).
Health: `GET /health`, `GET /ready`. Key endpoints: `/api/v1/system`, `/benchmarks` (+`/sync`, `/{id}/harbor-export`, `/{id}/archive`),
`/agents`, `/providers` (+`/{id}/test`), `/experiments` (+`/{id}/run`, `/{id}/compare`, `/{id}/report`),
`/trials/{id}` (+`/cancel`, `/retry`), `/analytics/failures`, `/analytics/security`, `/reports` (+`/{id}/download`, `/{id}/approve`),
`/approvals`, `/audit`, `/harbor/status`.
Auth: `X-API-Key` header. Roles viewer < operator < approver < admin. Approvals need approver/admin;
approving a FAIL gate needs `override_gate=true` + justification.
