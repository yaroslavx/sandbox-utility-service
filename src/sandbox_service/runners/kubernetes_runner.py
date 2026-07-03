import json
import time

from kubernetes import client, config
from kubernetes.client import ApiException

from sandbox_service.models import (
    Artifact,
    EffectiveRunLimits,
    Metrics,
    RunError,
    RunRequest,
    RunResponse,
    RunStatus,
)
from sandbox_service.runner import Runner
from sandbox_service.runners.kubernetes_specs import build_execution_spec
from sandbox_service.runtime.io import truncate_text
from sandbox_service.settings import Settings


class KubernetesJobRunner(Runner):
    def __init__(
        self,
        *,
        settings: Settings,
        batch_api: client.BatchV1Api | None = None,
        core_api: client.CoreV1Api | None = None,
        networking_api: client.NetworkingV1Api | None = None,
    ) -> None:
        self._settings = settings
        if batch_api is None or core_api is None or networking_api is None:
            _load_kubernetes_config()
        self._batch_api = batch_api or client.BatchV1Api()
        self._core_api = core_api or client.CoreV1Api()
        self._networking_api = networking_api or client.NetworkingV1Api()

    def run(
        self,
        *,
        run_id: str,
        request: RunRequest,
        limits: EffectiveRunLimits,
    ) -> RunResponse:
        spec = build_execution_spec(run_id=run_id, request=request, limits=limits, settings=self._settings)
        namespace = self._settings.kubernetes_namespace
        job_name = spec.job.metadata.name
        start = time.monotonic()

        try:
            self._core_api.create_namespaced_config_map(namespace=namespace, body=spec.config_map)
            try:
                self._networking_api.create_namespaced_network_policy(
                    namespace=namespace,
                    body=spec.network_policy,
                )
            except ApiException as exc:
                if exc.status not in {403, 404}:
                    raise
            self._batch_api.create_namespaced_job(namespace=namespace, body=spec.job)
            status = self._wait_for_job(namespace=namespace, job_name=job_name, timeout_s=limits.timeout_s + 10)
            pod_name = self._find_pod_name(namespace=namespace, job_name=job_name)
            logs = self._core_api.read_namespaced_pod_log(name=pod_name, namespace=namespace)
            response = _parse_wrapper_response(
                run_id=run_id,
                logs=logs,
                limits=limits,
                fallback_runtime_ms=_elapsed_ms(start),
            )
            if status == "timeout":
                return response.model_copy(
                    update={
                        "status": RunStatus.TIMEOUT,
                        "exit_code": None,
                        "error": RunError(code="timeout", message="execution timed out"),
                    }
                )
            return response
        finally:
            self._cleanup(namespace=namespace, job_name=job_name)

    def _wait_for_job(self, *, namespace: str, job_name: str, timeout_s: int) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            job = self._batch_api.read_namespaced_job_status(name=job_name, namespace=namespace)
            job_status = job.status
            if job_status.succeeded:
                return "complete"
            if job_status.failed:
                return "failed"
            time.sleep(self._settings.kubernetes_poll_interval_s)
        return "timeout"

    def _find_pod_name(self, *, namespace: str, job_name: str) -> str:
        pods = self._core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job-name={job_name}",
        )
        if not pods.items:
            raise RuntimeError(f"no pod found for job {job_name}")
        return pods.items[0].metadata.name

    def _cleanup(self, *, namespace: str, job_name: str) -> None:
        delete_options = client.V1DeleteOptions(propagation_policy="Background")
        with _ignore_missing():
            self._batch_api.delete_namespaced_job(
                name=job_name,
                namespace=namespace,
                body=delete_options,
            )
        with _ignore_missing():
            self._core_api.delete_namespaced_config_map(name=job_name, namespace=namespace)
        with _ignore_missing():
            self._networking_api.delete_namespaced_network_policy(name=job_name, namespace=namespace)


class _ignore_missing:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if isinstance(exc, ApiException) and exc.status == 404:
            return True
        return False


def _load_kubernetes_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _parse_wrapper_response(
    *,
    run_id: str,
    logs: str,
    limits: EffectiveRunLimits,
    fallback_runtime_ms: int,
) -> RunResponse:
    last_line = logs.strip().splitlines()[-1] if logs.strip() else "{}"
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError as exc:
        return RunResponse(
            run_id=run_id,
            status=RunStatus.INTERNAL_ERROR,
            stdout="",
            stderr=truncate_text(logs, limits.max_stderr_kb),
            exit_code=None,
            artifacts=[],
            metrics=Metrics(runtime_ms=fallback_runtime_ms),
            error=RunError(code="invalid_runner_output", message=str(exc)),
        )

    artifacts = [
        Artifact(
            name=item["name"],
            mime_type=item["mime_type"],
            size_bytes=item["size_bytes"],
            content_base64=item["content_base64"],
        )
        for item in payload.get("artifacts", [])
    ]
    status = RunStatus(payload.get("status", RunStatus.INTERNAL_ERROR))
    error_payload = payload.get("error")
    return RunResponse(
        run_id=run_id,
        status=status,
        stdout=truncate_text(payload.get("stdout", ""), limits.max_stdout_kb),
        stderr=truncate_text(payload.get("stderr", ""), limits.max_stderr_kb),
        exit_code=payload.get("exit_code"),
        artifacts=artifacts,
        metrics=Metrics(runtime_ms=payload.get("metrics", {}).get("runtime_ms", fallback_runtime_ms)),
        error=RunError(**error_payload) if error_payload else None,
    )


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))
