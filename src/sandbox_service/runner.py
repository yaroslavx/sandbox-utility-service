from abc import ABC, abstractmethod

from sandbox_service.models import EffectiveRunLimits, RunRequest, RunResponse
from sandbox_service.settings import Settings


class Runner(ABC):
    @abstractmethod
    def run(
        self,
        *,
        run_id: str,
        request: RunRequest,
        limits: EffectiveRunLimits,
    ) -> RunResponse:
        raise NotImplementedError


def create_runner(settings: Settings) -> Runner:
    if settings.runner == "fake":
        from sandbox_service.runners.fake import FakeRunner

        return FakeRunner()
    if settings.runner == "subprocess":
        from sandbox_service.runners.subprocess_runner import SubprocessRunner

        return SubprocessRunner()
    if settings.runner == "local-dev":
        from sandbox_service.runners.local_dev import LocalDevRunner

        return LocalDevRunner()
    if settings.runner == "kubernetes":
        from sandbox_service.runners.kubernetes_runner import KubernetesJobRunner

        return KubernetesJobRunner(settings=settings)

    raise ValueError(f"unsupported runner: {settings.runner}")
