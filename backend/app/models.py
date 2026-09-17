"""SQLAlchemy models for AgentEvalOps.

The schema is intentionally relational and auditable: immutable benchmark
versions, versioned agents, one row per trial, explicit approval and audit
records. Large artifacts live on disk and are referenced by path.
"""
import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Benchmark(Base):
    __tablename__ = "benchmarks"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(30), default="medium")
    category: Mapped[str] = mapped_column(String(80), default="general")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    instruction: Mapped[str] = mapped_column(Text, default="")
    manifest: Mapped[str] = mapped_column(Text, default="{}")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(40), default="native")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_task_version"),)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(30), default="1.0.0")
    provider: Mapped[str] = mapped_column(String(80), default="offline")
    model: Mapped[str] = mapped_column(String(160), default="none")
    prompt: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[str] = mapped_column(Text, default="[]")
    config: Mapped[str] = mapped_column(Text, default="{}")
    description: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_agent_name_version"),)


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    provider_type: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    api_key_masked: Mapped[str] = mapped_column(String(80), default="")
    api_key_env: Mapped[str] = mapped_column(String(120), default="")
    params: Mapped[str] = mapped_column(Text, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)
    repetitions: Mapped[int] = mapped_column(Integer, default=1)
    agent_ids: Mapped[str] = mapped_column(Text, default="[]")
    benchmark_ids: Mapped[str] = mapped_column(Text, default="[]")
    seed: Mapped[int] = mapped_column(Integer, default=42)
    baseline_experiment_id: Mapped[int] = mapped_column(Integer, nullable=True)
    policy: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(80), default="local-admin")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    trials = relationship("Trial", back_populates="experiment", cascade="all, delete-orphan")


class Trial(Base):
    __tablename__ = "trials"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey("benchmarks.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    repetition: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    reward: Mapped[float] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=True)
    failure_category: Mapped[str] = mapped_column(String(60), default="none", index=True)
    failure_detail: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[float] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=True)
    cost_provenance: Mapped[str] = mapped_column(String(200), default="unknown")
    trajectory_path: Mapped[str] = mapped_column(String(500), default="")
    artifact_dir: Mapped[str] = mapped_column(String(500), default="")
    artifact_bytes: Mapped[int] = mapped_column(Integer, default=0)
    verifier_evidence: Mapped[str] = mapped_column(Text, default="{}")
    verifier_version: Mapped[str] = mapped_column(String(40), default="1")
    classification_source: Mapped[str] = mapped_column(String(30), default="rule")
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    config_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    experiment = relationship("Experiment", back_populates="trials")
    __table_args__ = (Index("ix_trial_exp_agent_bench", "experiment_id", "agent_id", "benchmark_id"),)


class TrialEvent(Base):
    __tablename__ = "trial_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    trial_id: Mapped[int] = mapped_column(ForeignKey("trials.id"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")


class ReleaseReport(Base):
    __tablename__ = "release_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    baseline_experiment_id: Mapped[int] = mapped_column(Integer, nullable=True)
    gate_status: Mapped[str] = mapped_column(String(30))
    gate_reasons: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="{}")
    policy: Mapped[str] = mapped_column(Text, default="{}")
    markdown_path: Mapped[str] = mapped_column(String(500), default="")
    html_path: Mapped[str] = mapped_column(String(500), default="")
    json_path: Mapped[str] = mapped_column(String(500), default="")
    pdf_path: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(80), default="local-admin")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("release_reports.id"), nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    approver: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text, default="")
    override_gate: Mapped[bool] = mapped_column(Boolean, default=False)
    justification: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
