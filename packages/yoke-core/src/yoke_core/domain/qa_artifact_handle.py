"""Typed artifact handles — the only file reference on ``qa_artifacts``.

A handle is a small JSON document stored in ``qa_artifacts.artifact_handle``
that names WHERE the artifact bytes live, explicitly:

- ``{"backend": "s3", "bucket": B, "key": K, "content_type": CT?}`` —
  durable evidence uploaded to the project environment's artifacts bucket
  at the moment the artifact row was recorded.
- ``{"backend": "local", "path": P, "content_type": CT?}`` — an explicit
  machine-local reference (tests, ephemerals, repo-committed baselines).
  ``path`` is absolute or repo-relative; locality is declared, never
  inferred from a bare path string.

There is no bare-path compatibility shape: writers that try to record a
path without a backend get a typed denial naming this module's vocabulary.
S3 keys reuse the historical storage taxonomy
``qa-artifacts/{project}/{item_id}/{run_id}/{filename}`` so one capture's
local scratch layout and its durable key stay parallel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


BACKEND_S3 = "s3"
BACKEND_LOCAL = "local"
VALID_BACKENDS = frozenset({BACKEND_S3, BACKEND_LOCAL})

# Shared key/scratch taxonomy prefix (also used by the capture scratch tree
# in :mod:`yoke_core.domain.qa_artifacts`).
QA_ARTIFACT_STORAGE_KIND = "qa-artifacts"


class ArtifactHandleError(ValueError):
    """A handle payload is missing, malformed, or names an unknown backend."""


def safe_segment(value: str) -> str:
    """Validate one path/key segment (non-empty, no separators, no dots)."""
    text = str(value).strip()
    if not text or text in {".", ".."}:
        raise ArtifactHandleError("artifact key segment must be non-empty")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ArtifactHandleError(f"unsafe artifact key segment: {value!r}")
    return text


def build_artifact_key(
    project: str,
    item_id: int,
    run_id: int,
    filename: str,
) -> str:
    """Build the canonical S3 object key for one QA artifact.

    Format: ``qa-artifacts/{project}/{item_id}/{run_id}/{filename}``.
    """
    return (
        f"{QA_ARTIFACT_STORAGE_KIND}/{safe_segment(project)}/"
        f"{int(item_id)}/{int(run_id)}/{safe_segment(filename)}"
    )


def s3_handle(
    bucket: str, key: str, content_type: Optional[str] = None
) -> Dict[str, Any]:
    handle: Dict[str, Any] = {
        "backend": BACKEND_S3,
        "bucket": str(bucket),
        "key": str(key),
    }
    if content_type:
        handle["content_type"] = str(content_type)
    return validate_handle(handle)


def local_handle(
    path: str, content_type: Optional[str] = None
) -> Dict[str, Any]:
    handle: Dict[str, Any] = {"backend": BACKEND_LOCAL, "path": str(path)}
    if content_type:
        handle["content_type"] = str(content_type)
    return validate_handle(handle)


def validate_handle(handle: Any) -> Dict[str, Any]:
    """Validate a parsed handle dict; return it unchanged when well-formed."""
    if not isinstance(handle, dict):
        raise ArtifactHandleError(
            "artifact_handle must be a JSON object with a 'backend' field "
            f"(one of {sorted(VALID_BACKENDS)}), got {type(handle).__name__}"
        )
    backend = handle.get("backend")
    if backend not in VALID_BACKENDS:
        raise ArtifactHandleError(
            f"artifact_handle.backend must be one of {sorted(VALID_BACKENDS)}"
            f", got {backend!r}"
        )
    required = ("bucket", "key") if backend == BACKEND_S3 else ("path",)
    for field in required:
        value = handle.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ArtifactHandleError(
                f"artifact_handle backend {backend!r} requires a non-empty "
                f"string {field!r}"
            )
    return handle


def parse_handle(raw: Any) -> Dict[str, Any]:
    """Parse + validate a handle from a dict or its JSON text form."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ArtifactHandleError("artifact_handle is empty")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArtifactHandleError(
                f"artifact_handle is not valid JSON: {exc}"
            ) from exc
    return validate_handle(raw)


def serialize_handle(handle: Dict[str, Any]) -> str:
    """Canonical storage form: compact, key-sorted JSON."""
    return json.dumps(
        validate_handle(handle), sort_keys=True, separators=(",", ":")
    )


def handle_address(
    handle: Dict[str, Any], repo_root: Optional[str] = None
) -> str:
    """Return the honest absolute address of a handle.

    ``s3`` handles address as ``s3://bucket/key`` (a durable object URI,
    deliberately not a filesystem path). ``local`` handles address as a
    filesystem path: absolute paths pass through; relative paths join
    ``repo_root`` when given, else return unchanged.
    """
    handle = validate_handle(handle)
    if handle["backend"] == BACKEND_S3:
        return f"s3://{handle['bucket']}/{handle['key']}"
    path = Path(handle["path"])
    if path.is_absolute() or repo_root is None:
        return str(path)
    return str(Path(repo_root) / path)


def is_present(handle: Dict[str, Any], repo_root: Optional[str] = None) -> bool:
    """Evidence-presence predicate for lifecycle gates.

    ``local`` handles are present when the file exists on this machine's
    disk. ``s3`` handles are present by construction — the upload completed
    before the artifact row was recorded — and gates deliberately do not
    add network calls to re-verify the object.
    """
    handle = validate_handle(handle)
    if handle["backend"] == BACKEND_S3:
        return True
    return os.path.isfile(handle_address(handle, repo_root=repo_root))


__all__ = [
    "ArtifactHandleError",
    "BACKEND_LOCAL",
    "BACKEND_S3",
    "QA_ARTIFACT_STORAGE_KIND",
    "VALID_BACKENDS",
    "build_artifact_key",
    "handle_address",
    "is_present",
    "local_handle",
    "parse_handle",
    "s3_handle",
    "safe_segment",
    "serialize_handle",
    "validate_handle",
]
