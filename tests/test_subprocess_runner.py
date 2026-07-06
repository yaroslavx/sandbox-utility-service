import base64

import pytest

from sandbox_service.models import EffectiveRunLimits, RunInput, RunRequest, RunStatus
from sandbox_service.runners.local_dev import LocalDevRunner
from sandbox_service.runners.subprocess_runner import SubprocessRunner


def _limits(**overrides) -> EffectiveRunLimits:
    values = {
        "timeout_s": 5,
        "memory_mb": 512,
        "cpu_millis": 1000,
        "disk_mb": 256,
        "max_stdout_kb": 128,
        "max_stderr_kb": 128,
        "max_artifact_mb": 10,
    }
    values.update(overrides)
    return EffectiveRunLimits(**values)


def test_subprocess_runner_success_stdout() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(code="print(2 + 2)"),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.strip() == "4"
    assert response.exit_code == 0


def test_subprocess_runner_exception_maps_to_error() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(code="raise ValueError('bad math')"),
        limits=_limits(),
    )

    assert response.status == RunStatus.ERROR
    assert response.exit_code == 1
    assert "ValueError" in response.stderr
    assert response.error is not None
    assert response.error.code == "ValueError"


def test_subprocess_runner_timeout() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(code="while True:\n    pass\n"),
        limits=_limits(timeout_s=1),
    )

    assert response.status == RunStatus.TIMEOUT
    assert response.exit_code is None


def test_subprocess_runner_materializes_inputs() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code="print(open('data.txt').read())",
            inputs=[RunInput(name="data.txt", type="text", content_inline="hello")],
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.strip() == "hello"


def test_subprocess_runner_materializes_base64_file_input() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code="print(open('data.bin', 'rb').read().hex())",
            inputs=[
                RunInput(
                    name="data.bin",
                    type="file",
                    content_base64=base64.b64encode(b"\xCA\xFE").decode("ascii"),
                )
            ],
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.strip() == "cafe"


def test_subprocess_runner_captures_matplotlib_png() -> None:
    pytest.importorskip("matplotlib")

    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code=(
                "import matplotlib.pyplot as plt\n"
                "plt.plot([1, 2, 3], [1, 4, 9])\n"
                "plt.title('Squares')\n"
            )
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert len(response.artifacts) == 1
    artifact = response.artifacts[0]
    assert artifact.name == "figure_1.png"
    assert artifact.mime_type == "image/png"
    assert base64.b64decode(artifact.content_base64).startswith(b"\x89PNG")


def test_subprocess_runner_scrubs_parent_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHOULD_NOT_LEAK_TO_SANDBOX", "secret")

    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code=(
                "import os\n"
                "print(os.environ.get('SHOULD_NOT_LEAK_TO_SANDBOX', 'missing'))\n"
                "print(os.environ.get('MPLBACKEND'))\n"
            )
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.splitlines() == ["missing", "Agg"]


def test_subprocess_runner_truncates_stdout() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(code="print('a' * 4096)"),
        limits=_limits(max_stdout_kb=1),
    )

    assert response.status == RunStatus.SUCCESS
    assert "[truncated]" in response.stdout
    assert len(response.stdout.encode("utf-8")) <= 1024


def test_local_dev_runner_alias_still_works() -> None:
    response = LocalDevRunner().run(
        run_id="run-1",
        request=RunRequest(code="print('alias')"),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.strip() == "alias"
