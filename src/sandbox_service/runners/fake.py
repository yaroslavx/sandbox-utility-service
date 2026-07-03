from sandbox_service.models import (
    EffectiveRunLimits,
    Metrics,
    RunRequest,
    RunResponse,
    RunStatus,
)
from sandbox_service.runner import Runner


class FakeRunner(Runner):
    def run(
        self,
        *,
        run_id: str,
        request: RunRequest,
        limits: EffectiveRunLimits,
    ) -> RunResponse:
        _ = limits
        status = RunStatus.ERROR if "raise" in request.code else RunStatus.SUCCESS
        stderr = "fake error\n" if status == RunStatus.ERROR else ""
        exit_code = 1 if status == RunStatus.ERROR else 0
        return RunResponse(
            run_id=run_id,
            status=status,
            stdout=f"fake runner received {len(request.code)} bytes of code\n",
            stderr=stderr,
            exit_code=exit_code,
            artifacts=[],
            metrics=Metrics(runtime_ms=1),
        )
