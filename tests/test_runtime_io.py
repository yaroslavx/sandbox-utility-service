import base64

import pytest

from sandbox_service.models import RunInput
from sandbox_service.runtime.io import materialize_inputs, read_manifest_artifacts, truncate_text


def test_materialize_inputs_supports_inline_and_base64(tmp_path) -> None:
    materialize_inputs(
        [
            RunInput(name="hello.txt", type="text", content_inline="hello"),
            RunInput(
                name="nested/data.bin",
                type="file",
                content_base64=base64.b64encode(b"\x00\x01").decode("ascii"),
            ),
        ],
        tmp_path,
    )

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    assert (tmp_path / "nested" / "data.bin").read_bytes() == b"\x00\x01"


def test_materialize_inputs_rejects_workspace_escape(tmp_path) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        materialize_inputs(
            [RunInput(name="../secret.txt", type="text", content_inline="nope")],
            tmp_path,
        )


def test_truncate_text_adds_marker() -> None:
    value = truncate_text("a" * 2048, max_kb=1)

    assert len(value.encode("utf-8")) <= 1024
    assert "[truncated]" in value


def test_read_manifest_artifacts_enforces_total_limit(tmp_path) -> None:
    (tmp_path / "large.bin").write_bytes(b"x" * 2048)
    manifest = {"artifacts": [{"name": "large.bin", "mime_type": "application/octet-stream"}]}

    with pytest.raises(ValueError, match="artifact size limit exceeded"):
        read_manifest_artifacts(manifest, tmp_path, max_artifact_mb=0)
