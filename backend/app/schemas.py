"""Pydantic request models with strict validation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkIn(Strict):
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    version: str = Field(default="1.0.0", min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    difficulty: str = "medium"
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    instruction: str = ""
    verifier: str = "repo_repair"
    tools: list[str] = Field(default_factory=lambda: ["read_file", "write_file", "list_files"])
    allowed_commands: list[str] = Field(default_factory=list)
    prohibited_paths: list[str] = Field(default_factory=list)
    timeout_sec: int = Field(default=60, ge=1, le=3600)
    resource_limits: dict = Field(default_factory=dict)
    hidden_tests: str = ""

    @field_validator("difficulty")
    @classmethod
    def _difficulty(cls, v):
        if v not in ("easy", "medium", "hard", "expert"):
            raise ValueError("difficulty must be easy|medium|hard|expert")
        return v

    @field_validator("verifier")
    @classmethod
    def _verifier(cls, v):
        from .verifiers import VERIFIERS
        if v not in VERIFIERS:
            raise ValueError(f"verifier must be one of {sorted(VERIFIERS)}")
        return v


class AgentIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    version: str = Field(default="1.0.0", min_length=1, max_length=30)
    provider: str = "offline"
    model: str = "none"
    prompt: str = ""
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    description: str = ""

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("noop", "rule_based", "scripted_tool", "llm", "sleeper"):
            raise ValueError("kind must be noop|rule_based|scripted_tool|llm (sleeper is diagnostic only)")
        return v


class ProviderIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    provider_type: str
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=160)
    api_key: str = ""  # accepted for a one-time test only; never persisted
    api_key_env: str = Field(default="", max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$")
    params: dict = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("provider_type")
    @classmethod
    def _type(cls, v):
        from .providers import PROVIDER_TYPES
        if v not in PROVIDER_TYPES:
            raise ValueError(f"provider_type must be one of {PROVIDER_TYPES}")
        return v


class ProviderTestIn(Strict):
    api_key: str = ""  # transient, never persisted or logged


class ExperimentIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    agent_ids: list[int] = Field(min_length=1)
    benchmark_ids: list[int] = Field(min_length=1)
    repetitions: int = Field(default=1, ge=1, le=20)
    seed: int = 42
    baseline_experiment_id: int | None = None
    policy: dict = Field(default_factory=dict)

    @field_validator("agent_ids", "benchmark_ids")
    @classmethod
    def _unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("ids must be unique")
        return v


class ReportIn(Strict):
    baseline_experiment_id: int | None = None
    policy: dict = Field(default_factory=dict)


class ApprovalIn(Strict):
    decision: str
    approver: str = "local-approver"
    notes: str = ""
    override_gate: bool = False
    justification: str = ""

    @field_validator("decision")
    @classmethod
    def _decision(cls, v):
        if v not in ("approved", "rejected"):
            raise ValueError("decision must be approved|rejected")
        return v


class ClassificationIn(Strict):
    failure_category: str
    reviewer: str = "local-reviewer"
    notes: str = ""

    @field_validator("failure_category")
    @classmethod
    def _category(cls, v):
        from .classification import FAILURE_TAXONOMY
        if v not in FAILURE_TAXONOMY:
            raise ValueError(f"failure_category must be one of {FAILURE_TAXONOMY}")
        return v


class BenchmarkImportIn(Strict):
    manifest_text: str = Field(min_length=2)


class HarborImportIn(Strict):
    harbor_task_dir: str = Field(min_length=1)


class CleanupIn(Strict):
    older_than_days: int = Field(default=30, ge=1, le=3650)
    dry_run: bool = True


class HarborRunIn(Strict):
    args: list[str] = Field(default_factory=lambda: ["--help"])


class AgentCompareQuery(Strict):
    a: int
    b: int
