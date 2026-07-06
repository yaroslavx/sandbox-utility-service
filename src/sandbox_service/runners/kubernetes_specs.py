import json
from dataclasses import dataclass

from kubernetes import client

from sandbox_service.models import EffectiveRunLimits, RunRequest
from sandbox_service.settings import Settings


@dataclass(frozen=True)
class KubernetesExecutionSpec:
    config_map: client.V1ConfigMap
    job: client.V1Job
    network_policy: client.V1NetworkPolicy


def build_execution_spec(
    *,
    run_id: str,
    request: RunRequest,
    limits: EffectiveRunLimits,
    settings: Settings,
) -> KubernetesExecutionSpec:
    safe_run_id = run_id.replace("_", "-")
    name = f"python-sandbox-{safe_run_id}"
    labels = {
        "app.kubernetes.io/name": "sandbox-utility-service",
        "app.kubernetes.io/component": "python-execution",
        "sandbox.openai.com/run-id": run_id,
    }

    request_payload = request.model_dump(mode="json")
    config_map = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=name, namespace=settings.kubernetes_namespace, labels=labels),
        data={"request.json": json.dumps(request_payload)},
    )

    container = client.V1Container(
        name="runner",
        image=settings.kubernetes_runtime_image,
        image_pull_policy="IfNotPresent",
        command=[
            "python",
            "/opt/sandbox/runtime_wrapper.py",
            "--request-path",
            "/request/request.json",
            "--workspace",
            "/workspace",
            "--artifacts",
            "/artifacts",
            "--manifest",
            "/artifacts/manifest.json",
        ],
        env=[
            client.V1EnvVar(name="MPLBACKEND", value="Agg"),
            client.V1EnvVar(name="MPLCONFIGDIR", value="/tmp/matplotlib"),
            client.V1EnvVar(name="PYTHONUNBUFFERED", value="1"),
        ],
        resources=client.V1ResourceRequirements(
            requests={
                "cpu": f"{limits.cpu_millis}m",
                "memory": f"{limits.memory_mb}Mi",
                "ephemeral-storage": f"{limits.disk_mb}Mi",
            },
            limits={
                "cpu": f"{limits.cpu_millis}m",
                "memory": f"{limits.memory_mb}Mi",
                "ephemeral-storage": f"{limits.disk_mb}Mi",
            },
        ),
        security_context=client.V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
            read_only_root_filesystem=True,
            run_as_non_root=True,
            run_as_user=1000,
            run_as_group=1000,
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
        volume_mounts=[
            client.V1VolumeMount(name="request", mount_path="/request", read_only=True),
            client.V1VolumeMount(name="workspace", mount_path="/workspace"),
            client.V1VolumeMount(name="tmp", mount_path="/tmp"),
            client.V1VolumeMount(name="artifacts", mount_path="/artifacts"),
        ],
    )

    pod_spec = client.V1PodSpec(
        automount_service_account_token=False,
        restart_policy="Never",
        runtime_class_name=settings.kubernetes_runtime_class_name,
        service_account_name=settings.kubernetes_service_account_name,
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            run_as_group=1000,
            fs_group=1000,
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
        containers=[container],
        volumes=[
            client.V1Volume(
                name="request",
                config_map=client.V1ConfigMapVolumeSource(name=name),
            ),
            client.V1Volume(name="workspace", empty_dir=client.V1EmptyDirVolumeSource(size_limit=f"{limits.disk_mb}Mi")),
            client.V1Volume(name="tmp", empty_dir=client.V1EmptyDirVolumeSource(size_limit="64Mi")),
            client.V1Volume(name="artifacts", empty_dir=client.V1EmptyDirVolumeSource(size_limit=f"{limits.disk_mb}Mi")),
        ],
    )

    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=settings.kubernetes_namespace, labels=labels),
        spec=client.V1JobSpec(
            active_deadline_seconds=limits.timeout_s + 5,
            backoff_limit=settings.kubernetes_backoff_limit,
            ttl_seconds_after_finished=settings.kubernetes_job_ttl_seconds,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=pod_spec,
            ),
        ),
    )

    network_policy = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(name=name, namespace=settings.kubernetes_namespace, labels=labels),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels={"sandbox.openai.com/run-id": run_id}),
            policy_types=["Egress"],
            egress=[],
        ),
    )

    return KubernetesExecutionSpec(config_map=config_map, job=job, network_policy=network_policy)
