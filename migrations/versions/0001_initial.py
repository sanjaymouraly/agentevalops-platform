"""initial schema (AgentEvalOps 1.x)"""
import sys
from pathlib import Path

from alembic import op

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import models  # noqa: F401
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
