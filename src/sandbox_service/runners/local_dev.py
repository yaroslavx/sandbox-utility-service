import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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
from sandbox_service.runtime.io import materialize_inputs, read_manifest_artifacts, truncate_text
from sandbox_service.runners.kubernetes_runner import _parse_wrapper_response


class LocalDevRunner(Runner):
    """Local subprocess runner for developer smoke checks only.

    This is not a sandbox and must not be used in production.
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
            workspace.mkdir()
            artifacts.mkdir()
            code_path = workspace / "__user_code.py"
            code_path.write_text(request.code, encoding="utf-8")
            materialize_inputs(request.inputs, workspace)

            wrapper = Path(__file__).resolve().parents[1] / "runtime" / "runtime_wrapper.py"
            try:
                proc = subprocess.run(
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
                    capture_output=True,
                    text=True,
                    timeout=limits.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return RunResponse(
                    run_id=run_id,
                    status=RunStatus.TIMEOUT,
                    stdout=truncate_text(exc.stdout or "", limits.max_stdout_kb),
                    stderr=truncate_text(exc.stderr or "execution timed out", limits.max_stderr_kb),
                    exit_code=None,
                    artifacts=[],
                    metrics=Metrics(runtime_ms=_elapsed_ms(start)),
                    error=RunError(code="timeout", message="execution timed out"),
                )

            response = _parse_wrapper_response(
                run_id=run_id,
                logs=proc.stdout,
                limits=limits,
                fallback_runtime_ms=_elapsed_ms(start),
            )
            if proc.returncode != 0 and response.status == RunStatus.SUCCESS:
                return response.model_copy(
                    update={
                        "status": RunStatus.ERROR,
                        "exit_code": proc.returncode,
                        "stderr": truncate_text(proc.stderr, limits.max_stderr_kb),
                        "error": RunError(code="wrapper_error", message="runtime wrapper failed"),
                    }
                )
            return response


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))
