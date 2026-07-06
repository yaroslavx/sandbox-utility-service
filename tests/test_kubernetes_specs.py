from sandbox_service.models import EffectiveRunLimits, RunRequest
from sandbox_service.runners.kubernetes_specs import build_execution_spec
from sandbox_service.settings import Settings


def _limits() -> EffectiveRunLimits:
    return EffectiveRunLimits(
        timeout_s=20,
        memory_mb=512,
        cpu_millis=1000,
        disk_mb=256,
        max_stdout_kb=128,
        max_stderr_kb=128,
        max_artifact_mb=25,
    )


def test_kubernetes_job_spec_includes_hardening_defaults() -> None:
    settings = Settings(
        kubernetes_namespace="sandbox",
        kubernetes_runtime_image="runtime:dev",
        kubernetes_runtime_class_name="gvisor",
    )

    spec = build_execution_spec(
        run_id="abc-123",
        request=RunRequest(code="print('hi')"),
        limits=_limits(),
        settings=settings,
    )

    job = spec.job
    pod_spec = job.spec.template.spec
    container = pod_spec.containers[0]

    assert pod_spec.automount_service_account_token is False
    assert pod_spec.runtime_class_name == "gvisor"
    assert pod_spec.security_context.run_as_non_root is True
    assert container.security_context.allow_privilege_escalation is False
    assert container.security_context.read_only_root_filesystem is True
    assert container.security_context.capabilities.drop == ["ALL"]
    assert container.resources.limits["memory"] == "512Mi"
    assert container.resources.limits["cpu"] == "1000m"
    assert {env.name: env.value for env in container.env}["MPLCONFIGDIR"] == "/tmp/matplotlib"
    assert job.spec.active_deadline_seconds == 25
    assert {mount.mount_path for mount in container.volume_mounts} == {
        "/request",
        "/workspace",
        "/tmp",
        "/artifacts",
    }


def test_kubernetes_network_policy_denies_all_egress() -> None:
    spec = build_execution_spec(
        run_id="abc-123",
        request=RunRequest(code="print('hi')"),
        limits=_limits(),
        settings=Settings(),
    )

    assert spec.network_policy.spec.policy_types == ["Egress"]
    assert spec.network_policy.spec.egress == []
    assert spec.network_policy.spec.pod_selector.match_labels == {
        "sandbox.openai.com/run-id": "abc-123"
    }
