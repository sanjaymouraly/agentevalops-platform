"""Environment-driven configuration.

All settings use the ``AGENTEVALOPS_`` prefix and can be supplied through the
process environment or a local ``.env`` file. Secrets are never written to the
database; provider integrations reference environment variable *names*.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTEVALOPS_", env_file=".env", extra="ignore")

    app_name: str = "AgentEvalOps"
    version: str = "2.0.0"
    environment: str = "development"

    database_url: str = f"sqlite:///{ROOT / 'agentevalops.db'}"
    artifact_dir: Path = ROOT / "artifacts"
    benchmark_dir: Path = ROOT / "benchmarks" / "examples"
    harbor_dir: Path = ROOT / "benchmarks" / "harbor"

    # Local RBAC. Change all keys before exposing the service on a network.
    admin_key: str = "dev-admin-key-change-me"
    approver_key: str = "dev-approver-key-change-me"
    operator_key: str = "dev-operator-key-change-me"
    viewer_key: str = "dev-viewer-key-change-me"
    allow_anonymous: bool = True

    # Execution. "subprocess" is the safe local default (hard timeout + rlimits).
    # "docker" requires the runner image (scripts/build_runner.sh) and is the
    # recommended isolation mode for untrusted agent code. "local" is in-process.
    execution_mode: str = "subprocess"
    max_concurrency: int = 4
    trial_timeout_sec: int = 120
    max_steps: int = 8
    max_artifact_bytes: int = 10_000_000
    retention_days: int = 30
    docker_image: str = "agentevalops-runner:latest"
    docker_network: str = "none"
    verify_timeout_sec: int = 60

    # Optional convenience defaults (the dashboard can also store these names).
    ollama_base_url: str = "http://localhost:11434/v1"
    cors_origins: str = "*"

    # Budget guardrails surfaced in the UI; provider spend is never triggered
    # without an explicit experiment run and configured provider.
    monthly_budget_usd: float = Field(default=0.0, ge=0)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def resolved(self, path: Path | str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
