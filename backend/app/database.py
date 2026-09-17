from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()

if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first public schema. Kept as a tiny compatibility
# shim for SQLite dev databases; production upgrades use Alembic.
_ADDITIONS = {
    "agents": [
        ("prompt", "TEXT DEFAULT ''"), ("system_prompt", "TEXT DEFAULT ''"),
        ("tools", "TEXT DEFAULT '[]'"), ("archived", "BOOLEAN DEFAULT 0"),
    ],
    "benchmarks": [("source", "VARCHAR(40) DEFAULT 'native'")],
    "experiments": [
        ("baseline_experiment_id", "INTEGER"), ("policy", "TEXT DEFAULT '{}'"),
        ("started_at", "DATETIME"), ("finished_at", "DATETIME"),
    ],
    "trials": [
        ("cost_provenance", "VARCHAR(200) DEFAULT 'unknown'"),
        ("artifact_bytes", "INTEGER DEFAULT 0"),
        ("verifier_version", "VARCHAR(40) DEFAULT '1'"),
        ("classification_source", "VARCHAR(30) DEFAULT 'rule'"),
        ("classification_confidence", "FLOAT"),
        ("reviewer", "VARCHAR(120) DEFAULT ''"),
        ("error", "TEXT DEFAULT ''"),
        ("cancellation_requested", "BOOLEAN DEFAULT 0"),
        ("started_at", "DATETIME"),
    ],
    "release_reports": [("pdf_path", "VARCHAR(500) DEFAULT ''"), ("policy", "TEXT DEFAULT '{}'")],
}


def init_db():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDITIONS.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
