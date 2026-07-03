from fastapi import Depends, FastAPI, HTTPException, status

from sandbox_service.auth import require_internal_service
from sandbox_service.models import RunRequest, RunResponse
from sandbox_service.runner import Runner, create_runner
from sandbox_service.service import RunService
from sandbox_service.settings import Settings, get_settings


def get_runner(settings: Settings = Depends(get_settings)) -> Runner:
    return create_runner(settings)


def get_run_service(runner: Runner = Depends(get_runner)) -> RunService:
    return RunService(runner=runner)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sandbox Utility Service",
        version="0.1.0",
        description="Synchronous Python code execution service for AI tool calling.",
    )

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    def readyz(settings: Settings = Depends(get_settings)) -> dict[str, str]:
        return {"status": "ready", "runner": settings.runner}

    @app.post(
        "/v1/runs",
        response_model=RunResponse,
        status_code=status.HTTP_200_OK,
        tags=["runs"],
        dependencies=[Depends(require_internal_service)],
    )
    def run_python(
        request: RunRequest,
        service: RunService = Depends(get_run_service),
    ) -> RunResponse:
        try:
            return service.run(request)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return app
