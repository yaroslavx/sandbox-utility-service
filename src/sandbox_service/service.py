import time
import uuid

from sandbox_service.models import (
    Metrics,
    RunError,
    RunRequest,
    RunResponse,
    RunStatus,
)
from sandbox_service.runner import Runner
from sandbox_service.settings import get_settings


class RunService:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def run(self, request: RunRequest) -> RunResponse:
        settings = get_settings()
        limits = settings.effective_limits(request.limits)
        run_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            result = self._runner.run(run_id=run_id, request=request, limits=limits)
        except TimeoutError as exc:
            return RunResponse(
                run_id=run_id,
                status=RunStatus.TIMEOUT,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                artifacts=[],
                metrics=Metrics(runtime_ms=_elapsed_ms(start)),
                error=RunError(code="timeout", message=str(exc)),
            )
        except Exception as exc:  # pragma: no cover - defensive API boundary
            return RunResponse(
                run_id=run_id,
                status=RunStatus.INTERNAL_ERROR,
                stdout="",
                stderr="",
                exit_code=None,
                artifacts=[],
                metrics=Metrics(runtime_ms=_elapsed_ms(start)),
                error=RunError(code="internal_error", message=str(exc)),
            )

        return result.model_copy(update={"run_id": run_id})


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))
