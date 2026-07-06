import platform
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from sandbox_service.models import (
    EffectiveRunLimits,
    Metrics,
    RunError,
    RunRequest,
    RunResponse,
    RunStatus,
)
from sandbox_service.runner import Runner
from sandbox_service.runtime.io import materialize_inputs, truncate_text
from sandbox_service.runners.kubernetes_runner import _parse_wrapper_response


class SubprocessRunner(Runner):
    """Best-effort subprocess execution for the no-Kubernetes-RBAC MVP.

    This runner is useful for corporate environments where the API service
    cannot create Kubernetes Jobs. It is not a strong sandbox.
    """

    def run(
        self,
        *,
        run_id: str,
        request: RunRequest,
        limits: EffectiveRunLimits,
    ) -> RunResponse:
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"sandbox-{run_id}-") as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            artifacts = root / "artifacts"
            tmp = root / "tmp"
            workspace.mkdir()
            artifacts.mkdir()
            tmp.mkdir()
            code_path = workspace / "__user_code.py"
            code_path.write_text(request.code, encoding="utf-8")
            materialize_inputs(request.inputs, workspace)

            wrapper = Path(__file__).resolve().parents[1] / "runtime" / "runtime_wrapper.py"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(wrapper),
                    "--code-path",
                    str(code_path),
                    "--workspace",
                    str(workspace),
                    "--artifacts",
                    str(artifacts),
                    "--manifest",
                    str(artifacts / "manifest.json"),
                ],
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_child_env(root=root, tmp=tmp),
                preexec_fn=_child_preexec(limits),
                start_new_session=_use_process_group(),
            )
            try:
                stdout, stderr = proc.communicate(timeout=limits.timeout_s)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)
                stdout, stderr = proc.communicate()
                return RunResponse(
                    run_id=run_id,
                    status=RunStatus.TIMEOUT,
                    stdout=truncate_text(stdout or "", limits.max_stdout_kb),
                    stderr=truncate_text(stderr or "execution timed out", limits.max_stderr_kb),
                    exit_code=None,
                    artifacts=[],
                    metrics=Metrics(runtime_ms=_elapsed_ms(start)),
                    error=RunError(code="timeout", message="execution timed out"),
                )

            response = _parse_wrapper_response(
                run_id=run_id,
                logs=stdout,
                limits=limits,
                fallback_runtime_ms=_elapsed_ms(start),
            )
            if proc.returncode != 0 and response.status == RunStatus.SUCCESS:
                return response.model_copy(
                    update={
                        "status": RunStatus.ERROR,
                        "exit_code": proc.returncode,
                        "stderr": truncate_text(stderr, limits.max_stderr_kb),
                        "error": RunError(code="wrapper_error", message="runtime wrapper failed"),
                    }
                )
            return response


def _child_env(*, root: Path, tmp: Path) -> dict[str, str]:
    return {
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(tmp / "matplotlib"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": str(tmp),
    }


def _child_preexec(limits: EffectiveRunLimits) -> Callable[[], None] | None:
    if platform.system() != "Linux":
        return None

    def prepare_child() -> None:
        import os
        import resource

        os.umask(0o077)

        memory_bytes = limits.memory_mb * 1024 * 1024
        disk_bytes = limits.disk_mb * 1024 * 1024
        cpu_seconds = max(1, limits.timeout_s + 1)
        stack_bytes = 64 * 1024 * 1024

        _set_limit(resource.RLIMIT_AS, memory_bytes)
        _set_limit(resource.RLIMIT_CPU, cpu_seconds)
        _set_limit(resource.RLIMIT_FSIZE, disk_bytes)
        _set_limit(resource.RLIMIT_CORE, 0)
        _set_limit(resource.RLIMIT_NOFILE, 64)
        _set_limit(resource.RLIMIT_STACK, stack_bytes)
        if hasattr(resource, "RLIMIT_NPROC"):
            _set_limit(resource.RLIMIT_NPROC, 32)

    return prepare_child


def _set_limit(resource_name: int, value: int) -> None:
    import resource

    soft, hard = resource.getrlimit(resource_name)
    desired = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(resource_name, (desired, hard))


def _use_process_group() -> bool:
    return platform.system() != "Windows"


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if _use_process_group():
        try:
            import os

            os.killpg(proc.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    proc.kill()


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))
