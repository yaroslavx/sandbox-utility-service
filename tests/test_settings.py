from sandbox_service.models import RunLimits
from sandbox_service.settings import Settings


def test_effective_limits_apply_defaults() -> None:
    settings = Settings()

    limits = settings.effective_limits(RunLimits())

    assert limits.timeout_s == settings.default_timeout_s
    assert limits.memory_mb == settings.default_memory_mb
    assert limits.cpu_millis == settings.default_cpu_millis


def test_effective_limits_clamp_to_maximums() -> None:
    settings = Settings(max_timeout_s=30, max_memory_mb=2048, max_cpu_millis=2000)

    limits = settings.effective_limits(
        RunLimits(timeout_s=999, memory_mb=9999, cpu_millis=9999)
    )

    assert limits.timeout_s == 30
    assert limits.memory_mb == 2048
    assert limits.cpu_millis == 2000
