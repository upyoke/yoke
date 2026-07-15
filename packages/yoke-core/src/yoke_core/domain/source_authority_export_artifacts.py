"""Crash-safe publication for a source archive and its receipt sidecars."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import fcntl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoke_core.domain import universe_export
from yoke_core.domain.source_freeze_intent import write_owner_only_json


class SourceExportArtifactError(RuntimeError):
    """The archive receipt set could not be published safely."""


@dataclass
class ExportArtifactSet:
    final: Path
    staged: Path
    final_intent: Path
    final_receipt: Path
    staged_intent: Path
    staged_receipt: Path
    lock_descriptor: int | None


def prepare_artifact_set(
    out: str | Path, *, org_slug: str,
) -> ExportArtifactSet:
    final = universe_export.resolve_export_destination(out, org_slug)
    final_intent, final_receipt = _sidecars(final)
    descriptor = _acquire_publication_lock(final)
    try:
        _recover_or_refuse(final, final_intent, final_receipt)
        token = secrets.token_hex(8)
        staged = final.with_name(f".{final.name}.{token}.partial")
        staged_intent, staged_receipt = _sidecars(staged)
        return ExportArtifactSet(
            final=final, staged=staged,
            final_intent=final_intent, final_receipt=final_receipt,
            staged_intent=staged_intent, staged_receipt=staged_receipt,
            lock_descriptor=descriptor,
        )
    except Exception:
        os.close(descriptor)
        raise


def publish_artifact_set(
    artifact_set: ExportArtifactSet, *, intent: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    """Publish receipts first and the archive as the single commit marker."""
    published: list[Path] = []
    try:
        write_owner_only_json(artifact_set.staged_intent, intent)
        write_owner_only_json(artifact_set.staged_receipt, receipt)
        _fsync_file(artifact_set.staged)
        for staged, final in (
            (artifact_set.staged_intent, artifact_set.final_intent),
            (artifact_set.staged_receipt, artifact_set.final_receipt),
        ):
            os.link(staged, final, follow_symlinks=False)
            published.append(final)
        _fsync_directory(artifact_set.final.parent)
        os.link(
            artifact_set.staged, artifact_set.final, follow_symlinks=False,
        )
        published.append(artifact_set.final)
        _fsync_directory(artifact_set.final.parent)
    except Exception as exc:
        for path in reversed(published):
            path.unlink(missing_ok=True)
        _fsync_directory(artifact_set.final.parent)
        raise SourceExportArtifactError(
            "source export receipt set publication failed"
        ) from exc
    finally:
        cleanup_staged(artifact_set)


def cleanup_staged(artifact_set: ExportArtifactSet) -> None:
    for path in (
        artifact_set.staged, artifact_set.staged_intent,
        artifact_set.staged_receipt,
    ):
        path.unlink(missing_ok=True)
    if artifact_set.lock_descriptor is not None:
        fcntl.flock(artifact_set.lock_descriptor, fcntl.LOCK_UN)
        os.close(artifact_set.lock_descriptor)
        artifact_set.lock_descriptor = None


def _recover_or_refuse(final: Path, intent: Path, receipt: Path) -> None:
    if final.exists() or final.is_symlink():
        raise SourceExportArtifactError(
            f"source export artifact already exists: {final}"
        )
    _recover_staged(final)
    present = []
    for sidecar, schema in (
        (intent, "yoke.source-freeze/v1"),
        (receipt, None),
    ):
        if not sidecar.exists() and not sidecar.is_symlink():
            continue
        _require_owned_receipt(sidecar, schema=schema)
        present.append(sidecar)
    for sidecar in present:
        sidecar.unlink()
    _fsync_directory(final.parent)


def _recover_staged(final: Path) -> None:
    name = re.escape(final.name)
    allowed = re.compile(
        rf"^\.{name}\.[0-9a-f]{{16}}\.partial"
        rf"(?:\.source-freeze-(?:intent|receipt)\.json)?$"
    )
    prefix = f".{final.name}."
    candidates = [
        candidate
        for candidate in final.parent.iterdir()
        if candidate.name.startswith(prefix) and ".partial" in candidate.name
    ]
    for candidate in candidates:
        info = candidate.lstat()
        if (
            allowed.fullmatch(candidate.name) is None
            or stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SourceExportArtifactError(
                "incomplete source export staging artifact is unsafe"
            )
    for candidate in candidates:
        candidate.unlink()


def _require_owned_receipt(path: Path, *, schema: str | None) -> None:
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SourceExportArtifactError(
            "incomplete source export receipt is unsafe"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceExportArtifactError(
            "incomplete source export receipt is invalid"
        ) from exc
    observed = payload.get("schema") if schema is not None else payload.get(
        "freeze_intent", {}
    ).get("schema")
    if observed != "yoke.source-freeze/v1":
        raise SourceExportArtifactError(
            "incomplete source export receipt is unrelated"
        )


def _acquire_publication_lock(final: Path) -> int:
    lock = final.with_suffix(final.suffix + ".source-freeze.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags, 0o600)
    except OSError as exc:
        raise SourceExportArtifactError(
            "source export publication lock is unsafe"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SourceExportArtifactError(
                "source export publication lock is unsafe"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SourceExportArtifactError(
                "another source export is already active"
            ) from exc
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _sidecars(archive: Path) -> tuple[Path, Path]:
    return (
        archive.with_suffix(archive.suffix + ".source-freeze-intent.json"),
        archive.with_suffix(archive.suffix + ".source-freeze-receipt.json"),
    )


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ExportArtifactSet", "SourceExportArtifactError", "cleanup_staged",
    "prepare_artifact_set", "publish_artifact_set",
]
