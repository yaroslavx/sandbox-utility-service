from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputType(StrEnum):
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    FILE = "file"


class RuntimePreset(StrEnum):
    PYTHON_DATASCIENCE = "python-datascience"


class RunStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    KILLED = "killed"
    INTERNAL_ERROR = "internal_error"


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_./-]+$")]
    type: InputType
    content_inline: Annotated[str | None, Field(max_length=2_000_000)] = None
    content_base64: Annotated[str | None, Field(max_length=8_000_000)] = None
    mime_type: Annotated[str | None, Field(max_length=255)] = None

    @model_validator(mode="after")
    def require_exactly_one_content_source(self) -> "RunInput":
        has_inline = self.content_inline is not None
        has_base64 = self.content_base64 is not None
        if has_inline == has_base64:
            raise ValueError("input must include exactly one of content_inline or content_base64")
        parts = self.name.split("/")
        if self.name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("input name must be a safe relative path")
        return self


class RunLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_s: Annotated[int | None, Field(ge=1)] = None
    memory_mb: Annotated[int | None, Field(ge=64)] = None
    cpu_millis: Annotated[int | None, Field(ge=50)] = None
    disk_mb: Annotated[int | None, Field(ge=1)] = None
    max_stdout_kb: Annotated[int | None, Field(ge=1)] = None
    max_stderr_kb: Annotated[int | None, Field(ge=1)] = None
    max_artifact_mb: Annotated[int | None, Field(ge=1)] = None


class EffectiveRunLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeout_s: int
    memory_mb: int
    cpu_millis: int
    disk_mb: int
    max_stdout_kb: int
    max_stderr_kb: int
    max_artifact_mb: int


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[str | None, Field(max_length=256)] = None
    tenant_id: Annotated[str | None, Field(max_length=256)] = None
    conversation_id: Annotated[str | None, Field(max_length=256)] = None
    model_id: Annotated[str | None, Field(max_length=256)] = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=200_000)]
    inputs: Annotated[list[RunInput], Field(max_length=32)] = Field(default_factory=list)
    runtime: Literal[RuntimePreset.PYTHON_DATASCIENCE] = RuntimePreset.PYTHON_DATASCIENCE
    limits: RunLimits = Field(default_factory=RunLimits)
    metadata: RunMetadata = Field(default_factory=RunMetadata)


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    mime_type: str
    size_bytes: int
    content_base64: str


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_ms: int


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    stdout: str
    stderr: str
    exit_code: int | None
    artifacts: list[Artifact]
    metrics: Metrics
    error: RunError | None = None
