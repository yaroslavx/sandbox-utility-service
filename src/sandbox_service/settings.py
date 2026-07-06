from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sandbox_service.models import EffectiveRunLimits, RunLimits


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_", extra="ignore")

    runner: Literal["subprocess", "kubernetes", "fake"] = "subprocess"

    default_timeout_s: int = 20
    default_memory_mb: int = 512
    default_cpu_millis: int = 1000
    default_disk_mb: int = 256
    default_max_stdout_kb: int = 128
    default_max_stderr_kb: int = 128
    default_max_artifact_mb: int = 25

    max_timeout_s: int = 30
    max_memory_mb: int = 2048
    max_cpu_millis: int = 2000
    max_disk_mb: int = 500
    max_stdout_kb: int = 256
    max_stderr_kb: int = 256
    max_artifact_mb: int = 50

    kubernetes_namespace: str = "sandbox-executions"
    kubernetes_runtime_image: str = "sandbox-python-datascience:0.1.0"
    kubernetes_service_account_name: str = "default"
    kubernetes_runtime_class_name: str | None = None
    kubernetes_job_ttl_seconds: int = 300
    kubernetes_poll_interval_s: float = Field(default=0.5, ge=0.1)
    kubernetes_backoff_limit: int = 0

    def effective_limits(self, requested: RunLimits | None) -> EffectiveRunLimits:
        requested = requested or RunLimits()
        return EffectiveRunLimits(
            timeout_s=min(requested.timeout_s or self.default_timeout_s, self.max_timeout_s),
            memory_mb=min(requested.memory_mb or self.default_memory_mb, self.max_memory_mb),
            cpu_millis=min(requested.cpu_millis or self.default_cpu_millis, self.max_cpu_millis),
            disk_mb=min(requested.disk_mb or self.default_disk_mb, self.max_disk_mb),
            max_stdout_kb=min(
                requested.max_stdout_kb or self.default_max_stdout_kb,
                self.max_stdout_kb,
            ),
            max_stderr_kb=min(
                requested.max_stderr_kb or self.default_max_stderr_kb,
                self.max_stderr_kb,
            ),
            max_artifact_mb=min(
                requested.max_artifact_mb or self.default_max_artifact_mb,
                self.max_artifact_mb,
            ),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
