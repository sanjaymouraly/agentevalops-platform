import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import models  # noqa: F401
from app.database import Base

config = context.config
if config.config_file_name is not None and Path(config.config_file_name).exists():
    try: fileConfig(config.config_file_name)
    except Exception: pass
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    cfg = config.get_section(config.config_ini_section, {})
    import os
    if os.environ.get("AGENTEVALOPS_DATABASE_URL"): cfg["sqlalchemy.url"] = os.environ["AGENTEVALOPS_DATABASE_URL"].replace("+psycopg", "")
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
