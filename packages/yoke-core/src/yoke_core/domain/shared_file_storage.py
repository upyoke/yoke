"""Store and read shared files by project path, with no per-file record.

The project's configured artifacts bucket holds the bytes when one is
declared: a hosted tenant signs through its storage broker, a local or
self-hosted server signs with the project's ``aws-admin`` capability. With
no bucket, the bytes live in the permanent tree on the machine that serves
the universe. A configured bucket that fails is an error, never a silent
switch to disk.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_contracts.qa_evidence_plane import (
    administered_elsewhere_env,
    serving_env_label,
)
from yoke_contracts.shared_files import (
    SHARED_FILES_STORAGE_KIND,
    shared_file_content_type,
    shared_file_path,
    shared_file_project,
)

from yoke_core.domain.signed_object_transfer import (
    ObjectTransferError,
    get_signed_object,
    put_signed_object,
)

MAX_SHARED_FILE_BYTES = MAX_ARTIFACT_BYTES
SIGNED_URL_EXPIRES_S = 300


class SharedFileError(RuntimeError):
    """A shared file could not be stored or read; ``code`` names why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredSharedFile:
    backend: str
    address: str


@dataclass(frozen=True)
class _Bucket:
    bucket: str
    key: str
    broker: Any
    project_id: int
    project: str
    path: str


def local_shared_file_root() -> Path:
    """The serving machine's permanent shared-file tree."""
    from yoke_core.domain import machine_config

    return machine_config.yoke_home() / SHARED_FILES_STORAGE_KIND


def _local_path(project: str, path: str) -> Path:
    return local_shared_file_root().joinpath(project, *path.split("/"))


def _bucket(conn: Any, project_id: int, project: str, path: str) -> _Bucket | None:
    from yoke_core.domain.qa_artifact_configuration import (
        resolve_artifacts_bucket,
    )
    from yoke_core.domain.qa_artifact_broker import ArtifactBrokerError, broker_config

    try:
        configured = resolve_artifacts_bucket(conn, project_id, None)
        broker = broker_config()
    except ArtifactBrokerError as exc:
        raise SharedFileError(exc.code, str(exc)) from exc
    except ValueError as exc:
        raise SharedFileError("s3_configuration_invalid", str(exc)) from exc
    if configured is None:
        return None
    _environment, bucket, prefix = configured
    owner = f"{SHARED_FILES_STORAGE_KIND}/{project}/{path}"
    return _Bucket(
        bucket=bucket,
        key=f"{prefix}/{owner}" if prefix else owner,
        broker=broker,
        project_id=project_id,
        project=project,
        path=path,
    )


def _signed_url(conn: Any, store: _Bucket, method: str) -> str:
    from yoke_core.domain.qa_artifact_configuration import (
        _aws_region,
        _capability_credentials,
    )
    from yoke_core.domain.qa_artifact_broker import (
        ArtifactBrokerError,
        presign_shared_file_with_broker,
    )
    from yoke_core.domain.s3_presign import presign_s3_url

    if store.broker is not None:
        try:
            return presign_shared_file_with_broker(
                store.broker,
                operation=method.lower(),
                project=store.project,
                path=store.path,
            ).url
        except ArtifactBrokerError as exc:
            raise SharedFileError(exc.code, str(exc)) from exc
    region = _aws_region(conn, store.project_id)
    credentials = _capability_credentials(store.project)
    if not region or credentials is None:
        raise SharedFileError(
            "s3_configuration_invalid",
            f"project {store.project!r} declares artifacts bucket "
            f"{store.bucket!r} but its aws-admin capability region or "
            "credentials are unavailable; set the capability region, "
            "access_key_id and secret_access_key",
        )
    return presign_s3_url(
        method=method,
        bucket=store.bucket,
        key=store.key,
        region=region,
        credentials=credentials,
        expires_s=SIGNED_URL_EXPIRES_S,
    )


def _write_local(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, target)
    finally:
        if not handle.closed:
            handle.close()
        temporary.unlink(missing_ok=True)


def _local_write_refusal(project: str) -> str | None:
    admin = administered_elsewhere_env()
    if not admin:
        return None
    return (
        f"project {project!r} has no artifacts bucket, so the file would be "
        f"written to this machine's disk through database door {admin!r}, "
        "where no other client can read it. Upload through the https "
        f"connection that serves the universe (`--env {serving_env_label(admin)}`)."
    )


def put_shared_file(
    conn: Any, *, project_id: int, project: str, path: str, content: bytes
) -> StoredSharedFile:
    """Durably store ``content`` at the project path; refuse rather than move."""
    project = shared_file_project(project)
    path = shared_file_path(path)
    if not content:
        raise SharedFileError("shared_file_empty", "the file to upload is empty")
    if len(content) > MAX_SHARED_FILE_BYTES:
        raise SharedFileError(
            "shared_file_too_large",
            f"the file is {len(content)} bytes; the limit is {MAX_SHARED_FILE_BYTES}",
        )
    store = _bucket(conn, project_id, project, path)
    if store is None:
        refusal = _local_write_refusal(project)
        if refusal is not None:
            raise SharedFileError("shared_file_not_portable", refusal)
        target = _local_path(project, path)
        try:
            _write_local(target, content)
        except OSError as exc:
            raise SharedFileError(
                "local_storage_failed",
                f"permanent shared-file storage failed at {target}: {exc}",
            ) from exc
        return StoredSharedFile(backend="local", address=str(target))
    try:
        put_signed_object(
            _signed_url(conn, store, "PUT"),
            bucket=store.bucket,
            key=store.key,
            content=content,
            content_type=shared_file_content_type(path),
        )
    except ObjectTransferError as exc:
        raise SharedFileError(exc.code, str(exc)) from exc
    return StoredSharedFile(backend="s3", address=f"s3://{store.bucket}/{store.key}")


def read_shared_file(conn: Any, *, project_id: int, project: str, path: str) -> bytes:
    """Return the bytes stored at the project path."""
    project = shared_file_project(project)
    path = shared_file_path(path)
    store = _bucket(conn, project_id, project, path)
    if store is None:
        target = _local_path(project, path)
        if not target.is_file():
            raise SharedFileError(
                "shared_file_not_found",
                f"no shared file {path!r} in project {project!r} on this server",
            )
        if target.stat().st_size > MAX_SHARED_FILE_BYTES:
            raise SharedFileError(
                "shared_file_too_large",
                f"{target} exceeds the {MAX_SHARED_FILE_BYTES}-byte read limit",
            )
        return target.read_bytes()
    try:
        return get_signed_object(
            _signed_url(conn, store, "GET"),
            bucket=store.bucket,
            key=store.key,
            max_bytes=MAX_SHARED_FILE_BYTES,
        )
    except ObjectTransferError as exc:
        if exc.code == "s3_object_missing":
            raise SharedFileError(
                "shared_file_not_found",
                f"no shared file {path!r} in project {project!r}: {exc}",
            ) from exc
        raise SharedFileError(exc.code, str(exc)) from exc


__all__ = [
    "MAX_SHARED_FILE_BYTES",
    "SharedFileError",
    "StoredSharedFile",
    "local_shared_file_root",
    "put_shared_file",
    "read_shared_file",
]
