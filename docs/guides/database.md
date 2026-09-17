# Database & Migrations
Dev/default: SQLite (`AGENTEVALOPS_DATABASE_URL=sqlite:///./agentevalops.db`), tables created by
SQLAlchemy `create_all` on startup (idempotent, exercised from a fresh DB in CI/tests).
Production: set `AGENTEVALOPS_DATABASE_URL=postgresql+psycopg://…` (Docker Compose does this) —
the same models run unchanged. Schema evolution: Alembic is wired up (`alembic.ini`, `migrations/env.py`,
`migrations/versions/0001_initial.py`) — verified with `alembic upgrade head` on a fresh DB.
Add new migrations with `alembic revision --autogenerate -m "..."` against
`app.models.Base.metadata`; the app also applies two lightweight add-column migrations at
startup for pre-existing local SQLite DBs. Do not edit a released benchmark/agent row in
place — benchmarks and agents are versioned instead.
Persistence check: restart the API and confirm `/api/v1/system` trial counts are unchanged.
