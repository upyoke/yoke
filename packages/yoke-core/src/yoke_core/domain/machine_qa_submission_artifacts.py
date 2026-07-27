"""Secret guards and artifact transfer for Machine QA result submissions."""

from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from yoke_core.domain.qa_artifact_handle import (
    local_handle,
    parse_handle,
    safe_segment,
)
from yoke_harness.machine_qa_result_safety import ensure_secret_free_result


MAX_SUBMISSION_ARTIFACT_BYTES = 16 * 1024 * 1024


class MachineQaSubmissionArtifact(BaseModel):
    """One client-local capture transported to server-owned persistence."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)


def pack_local_artifacts(
    evidence: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[MachineQaSubmissionArtifact],
    tuple[Path, ...],
]:
    """Replace local handles with tokens and inline their bytes for submit."""
    artifacts: list[MachineQaSubmissionArtifact] = []
    source_paths: list[Path] = []

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            copied = {str(key): visit(child) for key, child in value.items()}
            raw_handle = copied.get("artifact_handle")
            if isinstance(raw_handle, dict):
                handle = parse_handle(raw_handle)
                if handle["backend"] != "local":
                    return copied
                source = Path(str(handle["path"])).expanduser()
                if not source.is_file():
                    raise ValueError(f"host-control artifact is unavailable: {source}")
                content = source.read_bytes()
                if len(content) > MAX_SUBMISSION_ARTIFACT_BYTES:
                    raise ValueError(
                        f"host-control artifact exceeds "
                        f"{MAX_SUBMISSION_ARTIFACT_BYTES} bytes"
                    )
                token = f"capture-{len(artifacts) + 1}"
                content_type = str(
                    handle.get("content_type") or "application/octet-stream"
                )
                artifacts.append(
                    MachineQaSubmissionArtifact(
                        token=token,
                        filename=safe_segment(source.name),
                        content_type=content_type,
                        content_base64=base64.b64encode(content).decode("ascii"),
                    )
                )
                source_paths.append(source)
                copied.pop("artifact_handle", None)
                copied["artifact_token"] = token
            return copied
        if isinstance(value, list):
            return [visit(child) for child in value]
        if isinstance(value, tuple):
            return [visit(child) for child in value]
        return value

    packed = visit(deepcopy(evidence))
    ensure_secret_free_result(packed)
    return packed, artifacts, tuple(source_paths)


def restore_submission_artifacts(
    evidence: dict[str, Any],
    artifacts: Iterable[MachineQaSubmissionArtifact],
    *,
    target_dir: Path,
) -> dict[str, Any]:
    """Write submitted bytes server-side and restore typed local handles."""
    target_dir.mkdir(parents=True, exist_ok=True)
    indexed: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.token in indexed:
            raise ValueError(
                f"duplicate host-control artifact token {artifact.token!r}"
            )
        try:
            content = base64.b64decode(
                artifact.content_base64,
                validate=True,
            )
        except ValueError as exc:
            raise ValueError(
                f"host-control artifact {artifact.token!r} is not base64"
            ) from exc
        if len(content) > MAX_SUBMISSION_ARTIFACT_BYTES:
            raise ValueError(
                f"host-control artifact exceeds {MAX_SUBMISSION_ARTIFACT_BYTES} bytes"
            )
        filename = safe_segment(artifact.filename)
        path = target_dir / f"{safe_segment(artifact.token)}-{filename}"
        path.write_bytes(content)
        indexed[artifact.token] = local_handle(
            str(path.resolve()),
            artifact.content_type,
        )
    consumed: set[str] = set()

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            copied = {str(key): visit(child) for key, child in value.items()}
            token = copied.pop("artifact_token", None)
            if token is not None:
                token = str(token)
                if token not in indexed:
                    raise ValueError(
                        f"host-control result references unknown artifact {token!r}"
                    )
                consumed.add(token)
                copied["artifact_handle"] = indexed[token]
            return copied
        if isinstance(value, list):
            return [visit(child) for child in value]
        if isinstance(value, tuple):
            return [visit(child) for child in value]
        return value

    restored = visit(deepcopy(evidence))
    unused = sorted(set(indexed) - consumed)
    if unused:
        raise ValueError(
            "host-control submission contains unreferenced artifacts: "
            + ", ".join(unused)
        )
    ensure_secret_free_result(restored)
    return restored


__all__ = [
    "MAX_SUBMISSION_ARTIFACT_BYTES",
    "MachineQaSubmissionArtifact",
    "ensure_secret_free_result",
    "pack_local_artifacts",
    "restore_submission_artifacts",
]
