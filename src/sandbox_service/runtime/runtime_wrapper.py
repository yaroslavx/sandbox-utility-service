import argparse
import base64
import contextlib
import io
import json
import mimetypes
import os
import runpy
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-path")
    parser.add_argument("--code-path")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    artifacts_dir = Path(args.artifacts)
    manifest_path = Path(args.manifest)
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if args.request_path:
        request = json.loads(Path(args.request_path).read_text(encoding="utf-8"))
        code_path = workspace / "__user_code.py"
        code_path.write_text(request["code"], encoding="utf-8")
        _materialize_request_inputs(request.get("inputs", []), workspace)
    elif args.code_path:
        code_path = Path(args.code_path)
    else:
        raise SystemExit("one of --request-path or --code-path is required")

    start = time.monotonic()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    exit_code = 0
    status = "success"
    error: dict[str, str] | None = None

    os.environ["MPLBACKEND"] = "Agg"
    os.environ.setdefault("MPLCONFIGDIR", str(workspace / ".matplotlib"))
    old_argv = sys.argv[:]
    old_path = sys.path[:]
    sys.argv = [str(code_path)]
    sys.path.insert(0, str(workspace))
    workspace_snapshot = _snapshot_workspace(workspace)

    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            runpy.run_path(str(code_path), run_name="__main__")
    except SystemExit as exc:
        exit_code = _system_exit_code(exc)
        if exit_code != 0:
            status = "error"
            error = {"code": "system_exit", "message": f"process exited with code {exit_code}"}
    except BaseException as exc:  # noqa: BLE001 - wrapper must catch user code failures
        exit_code = 1
        status = "error"
        stderr_buffer.write(traceback.format_exc())
        error = {"code": exc.__class__.__name__, "message": str(exc)}
    finally:
        sys.argv = old_argv
        sys.path = old_path

    artifacts = _capture_workspace_artifacts(
        workspace=workspace,
        artifacts_dir=artifacts_dir,
        baseline=workspace_snapshot,
        excluded_paths={code_path.resolve()},
    )
    artifacts.extend(
        _capture_matplotlib_figures(
            artifacts_dir=artifacts_dir,
            existing_names={item["name"] for item in artifacts},
        )
    )
    manifest = {"artifacts": artifacts}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = {
        "status": status,
        "stdout": stdout_buffer.getvalue(),
        "stderr": stderr_buffer.getvalue(),
        "exit_code": exit_code,
        "artifacts": _inline_artifacts(artifacts, artifacts_dir),
        "metrics": {"runtime_ms": max(0, round((time.monotonic() - start) * 1000))},
        "error": error,
    }
    print(json.dumps(result))
    return 0


def _system_exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1


def _materialize_request_inputs(inputs: list[dict[str, Any]], workspace: Path) -> None:
    workspace_root = workspace.resolve()
    for item in inputs:
        target = (workspace / item["name"]).resolve()
        if workspace_root not in target.parents and target != workspace_root:
            raise ValueError(f"input path escapes workspace: {item['name']}")
        if item.get("content_inline") is not None:
            content = item["content_inline"].encode("utf-8")
        else:
            content = base64.b64decode(item["content_base64"], validate=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _snapshot_workspace(workspace: Path) -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}
    workspace_root = workspace.resolve()
    for path in workspace_root.rglob("*"):
        if not path.is_file() or _is_ignored_workspace_path(path.relative_to(workspace_root)):
            continue
        stat = path.stat()
        snapshot[path.resolve()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _capture_workspace_artifacts(
    *,
    workspace: Path,
    artifacts_dir: Path,
    baseline: dict[Path, tuple[int, int]],
    excluded_paths: set[Path],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    workspace_root = workspace.resolve()
    for source in sorted(workspace_root.rglob("*")):
        if not source.is_file():
            continue
        resolved = source.resolve()
        if resolved in excluded_paths:
            continue
        relative = source.relative_to(workspace_root)
        if _is_ignored_workspace_path(relative):
            continue
        stat = source.stat()
        if baseline.get(resolved) == (stat.st_size, stat.st_mtime_ns):
            continue
        name = relative.as_posix()
        target = artifacts_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        artifacts.append(
            {
                "name": name,
                "mime_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "size_bytes": target.stat().st_size,
            }
        )
    return artifacts


def _is_ignored_workspace_path(relative: Path) -> bool:
    return any(part == "__pycache__" or part.startswith(".") for part in relative.parts)


def _capture_matplotlib_figures(
    artifacts_dir: Path,
    *,
    existing_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    artifacts: list[dict[str, Any]] = []
    used_names = set(existing_names or set())
    for index, fig_num in enumerate(plt.get_fignums(), start=1):
        fig = plt.figure(fig_num)
        name = _unique_artifact_name(f"figure_{index}.png", used_names)
        path = artifacts_dir / name
        fig.savefig(path, dpi=144, bbox_inches="tight")
        used_names.add(name)
        artifacts.append(
            {
                "name": name,
                "mime_type": "image/png",
                "size_bytes": path.stat().st_size,
            }
        )
    plt.close("all")
    return artifacts


def _unique_artifact_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        return name
    path = Path(name)
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10_000):
        candidate = f"{stem}_{index}{suffix}"
        if candidate not in used_names:
            return candidate
    raise RuntimeError(f"could not allocate artifact name for {name}")


def _inline_artifacts(artifacts: list[dict[str, Any]], artifacts_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in artifacts:
        path = artifacts_dir / item["name"]
        content = path.read_bytes()
        result.append(
            {
                "name": item["name"],
                "mime_type": item.get("mime_type")
                or mimetypes.guess_type(item["name"])[0]
                or "application/octet-stream",
                "size_bytes": len(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
