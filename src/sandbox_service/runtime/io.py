import base64
import binascii
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from sandbox_service.models import RunInput


@dataclass(frozen=True)
class ManifestArtifact:
    name: str
    mime_type: str
    size_bytes: int
    content: bytes


def truncate_text(value: str | bytes | None, max_kb: int) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    max_bytes = max_kb * 1024
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = "\n...[truncated]\n"
    suffix_bytes = suffix.encode("utf-8")
    kept = encoded[: max(0, max_bytes - len(suffix_bytes))]
    return kept.decode("utf-8", errors="ignore") + suffix


def materialize_inputs(inputs: list[RunInput], workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for item in inputs:
        target = (workspace / item.name).resolve()
        if workspace.resolve() not in target.parents and target != workspace.resolve():
            raise ValueError(f"input path escapes workspace: {item.name}")
        if item.content_inline is not None:
            data = item.content_inline.encode("utf-8")
        elif item.content_base64 is not None:
            try:
                data = base64.b64decode(item.content_base64, validate=True)
            except binascii.Error as exc:
                raise ValueError(f"invalid base64 for input {item.name}") from exc
        else:
            raise ValueError(f"input has no content: {item.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def read_manifest_artifacts(
    manifest: dict,
    artifacts_dir: Path,
    max_artifact_mb: int,
) -> list[ManifestArtifact]:
    max_bytes = max_artifact_mb * 1024 * 1024
    result: list[ManifestArtifact] = []
    total = 0
    for item in manifest.get("artifacts", []):
        name = str(item["name"])
        path = (artifacts_dir / name).resolve()
        if artifacts_dir.resolve() not in path.parents and path != artifacts_dir.resolve():
            continue
        if not path.is_file():
            continue
        content = path.read_bytes()
        total += len(content)
        if total > max_bytes:
            raise ValueError("artifact size limit exceeded")
        mime_type = item.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        result.append(
            ManifestArtifact(
                name=name,
                mime_type=mime_type,
                size_bytes=len(content),
                content=content,
            )
        )
    return result
