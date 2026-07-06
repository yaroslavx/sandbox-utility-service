import base64
import platform
import sys
import types

import pytest

from sandbox_service.models import EffectiveRunLimits, RunInput, RunRequest, RunStatus
from sandbox_service.runners import subprocess_runner
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


def test_subprocess_runner_sets_python_no_user_site() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code=(
                "import os\n"
                "print(os.environ.get('PYTHONNOUSERSITE'))\n"
            )
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    assert response.stdout.strip() == "1"


def test_subprocess_runner_uses_process_group_on_unix() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(
            code=(
                "import os\n"
                "print(os.getsid(0) == os.getpid())\n"
            )
        ),
        limits=_limits(),
    )

    assert response.status == RunStatus.SUCCESS
    if platform.system() == "Windows":
        assert response.stdout.strip() == "False"
    else:
        assert response.stdout.strip() == "True"


def test_subprocess_runner_truncates_stdout() -> None:
    response = SubprocessRunner().run(
        run_id="run-1",
        request=RunRequest(code="print('a' * 4096)"),
        limits=_limits(max_stdout_kb=1),
    )

    assert response.status == RunStatus.SUCCESS
    assert "[truncated]" in response.stdout
    assert len(response.stdout.encode("utf-8")) <= 1024


def test_linux_child_preexec_sets_additional_resource_limits(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = types.SimpleNamespace(
        RLIM_INFINITY=-1,
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        RLIMIT_FSIZE=3,
        RLIMIT_CORE=4,
        RLIMIT_NOFILE=5,
        RLIMIT_STACK=6,
        RLIMIT_NPROC=7,
        getrlimit=lambda _name: (-1, -1),
        setrlimit=lambda name, value: calls.append((name, value)),
    )
    fake_os = types.SimpleNamespace(umask=lambda _mask: None)
    monkeypatch.setattr(subprocess_runner.platform, "system", lambda: "Linux")
    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setitem(sys.modules, "os", fake_os)

    preexec = subprocess_runner._child_preexec(_limits(timeout_s=3, memory_mb=128, disk_mb=10))

    assert preexec is not None
    preexec()

    resource_names = {name for name, _value in calls}
    assert resource_names == {1, 2, 3, 4, 5, 6, 7}
    assert (4, (0, -1)) in calls
    assert (5, (64, -1)) in calls
