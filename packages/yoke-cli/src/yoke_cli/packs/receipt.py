"""Project-authoritative Pack receipt validation and atomic persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from yoke_contracts.packs import PACK_RECEIPT_REL, PACK_RECEIPT_SCHEMA


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PackReceiptError(RuntimeError):
    """The local Pack receipt is unsafe or invalid."""


def empty_receipt(project_id: int, project_slug: str) -> dict[str, Any]:
    return {
        "schema": PACK_RECEIPT_SCHEMA,
        "project_id": project_id,
        "project_slug": project_slug,
        "packs": {},
    }


def load_receipt(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / PACK_RECEIPT_REL
    _assert_safe_path(repo_root, PACK_RECEIPT_REL, allow_receipt=True)
    if path.is_symlink():
        raise PackReceiptError("Pack receipt must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise PackReceiptError("Pack receipt is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackReceiptError(f"Pack receipt is unreadable: {exc}") from exc
    validate_receipt(payload)
    return dict(payload)


def validate_receipt(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "project_id", "project_slug", "packs"
    }:
        raise PackReceiptError("Pack receipt has an unsupported shape")
    if payload.get("schema") != PACK_RECEIPT_SCHEMA:
        raise PackReceiptError("Pack receipt schema is unsupported")
    if not isinstance(payload.get("project_id"), int) or payload["project_id"] <= 0:
        raise PackReceiptError("Pack receipt project_id must be positive")
    if not isinstance(payload.get("project_slug"), str) or not payload["project_slug"]:
        raise PackReceiptError("Pack receipt project_slug is missing")
    packs = payload.get("packs")
    if not isinstance(packs, dict):
        raise PackReceiptError("Pack receipt packs must be an object")
    for slug, record in packs.items():
        if not isinstance(slug, str) or not isinstance(record, dict):
            raise PackReceiptError("Pack receipt contains an invalid Pack record")
        if set(record) != {"version", "content_digest", "render_values", "files"}:
            raise PackReceiptError(f"Pack receipt record {slug!r} is invalid")
        if not isinstance(record["version"], str) or not record["version"]:
            raise PackReceiptError(f"Pack receipt version {slug!r} is invalid")
        if (
            not isinstance(record["content_digest"], str)
            or not _SHA256.fullmatch(record["content_digest"])
        ):
            raise PackReceiptError(f"Pack receipt content digest {slug!r} is invalid")
        if not isinstance(record["render_values"], dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in record["render_values"].items()
        ):
            raise PackReceiptError(f"Pack receipt render values {slug!r} are invalid")
        if not isinstance(record["files"], dict):
            raise PackReceiptError(f"Pack receipt files {slug!r} are invalid")
        for path, file_record in record["files"].items():
            _validate_relative_path(path)
            if (
                not isinstance(file_record, dict)
                or set(file_record) != {"sha256", "mode"}
                or not isinstance(file_record["sha256"], str)
                or not _SHA256.fullmatch(file_record["sha256"])
                or file_record["mode"] not in (0o644, 0o755)
            ):
                raise PackReceiptError(f"Pack receipt file {path!r} is invalid")


def write_receipt(repo_root: Path, receipt: Mapping[str, Any]) -> Path:
    validate_receipt(receipt)
    _assert_safe_path(repo_root, PACK_RECEIPT_REL, allow_receipt=True)
    path = repo_root / PACK_RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    fd, raw_temp = tempfile.mkstemp(prefix=".packs.json.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o644)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return path


def _assert_safe_path(
    repo_root: Path, raw: str, *, allow_receipt: bool = False
) -> None:
    _validate_relative_path(raw, allow_receipt=allow_receipt)
    root = repo_root.resolve()
    current = root
    for part in Path(raw).parts:
        current = current / part
        if current.is_symlink():
            raise PackReceiptError(f"Pack path {raw!r} crosses symlink {current}")
    resolved = (root / raw).resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise PackReceiptError(f"Pack path {raw!r} resolves outside the checkout")


def assert_pack_targets_safe(repo_root: Path, paths: list[str]) -> None:
    for raw in paths:
        _assert_safe_path(repo_root, raw)
        target = repo_root / raw
        if target.exists() and not target.is_file():
            raise PackReceiptError(f"Pack target {raw!r} is not a regular file")


def _validate_relative_path(raw: str, *, allow_receipt: bool = False) -> None:
    if not isinstance(raw, str):
        raise PackReceiptError(f"Pack path is unsafe: {raw!r}")
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts[0] == ".yoke" and not (allow_receipt and raw == PACK_RECEIPT_REL))
    ):
        raise PackReceiptError(f"Pack path is unsafe: {raw!r}")


__all__ = [
    "PackReceiptError",
    "assert_pack_targets_safe",
    "empty_receipt",
    "load_receipt",
    "validate_receipt",
    "write_receipt",
]
