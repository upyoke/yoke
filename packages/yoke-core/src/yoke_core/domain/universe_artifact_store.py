"""Bounded file transfer using explicit source handles and destination stores."""

from __future__ import annotations

from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_core.domain import json_helper, machine_config
from yoke_core.domain.aws_machine_client import (
    machine_aws_client,
    safe_aws_error_reason,
)
from yoke_core.domain.handlers.qa_artifact_presign import (
    _aws_region,
    resolve_artifacts_bucket,
)
from yoke_core.domain.qa_artifact_handle import local_handle, s3_handle
from yoke_core.domain.universe_archive import UniverseArchiveError


def project_stores(conn: Any) -> dict[str, dict]:
    """Capture routing before a restore replaces the destination database."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "projects"):
        return {}
    stores = {}
    for project_id, slug in conn.execute("SELECT id, slug FROM projects").fetchall():
        configured = resolve_artifacts_bucket(conn, int(project_id), None)
        stores[str(slug)] = {
            "bucket": configured[1] if configured else None,
            "prefix": configured[2] if configured else None,
            "region": _aws_region(conn, int(project_id)),
            "environment": configured[0] if configured else None,
        }
    return stores


def _client(project: str, store: dict):
    if not store.get("region"):
        raise UniverseArchiveError(
            "archive_artifact_store_unavailable: source or destination S3 region "
            "is missing; configure the machine's aws-admin capability and retry"
        )
    return machine_aws_client("s3", project, store["region"])


@contextmanager
def read_handle(
    handle: dict,
    *,
    project: str,
    store: dict,
    repo_root: str | None = None,
    client_factory: Callable[[str, dict], Any] | None = None,
) -> Iterator[Any]:
    """Read the original handle; injected clients own credentials and region."""
    if handle["backend"] == "local":
        path = Path(handle["path"])
        if not path.is_absolute():
            if not repo_root:
                raise OSError("relative source path has no project checkout")
            path = Path(repo_root) / path
        with path.open("rb") as stream:
            yield stream
    else:
        response = (client_factory or _client)(project, store).get_object(
            Bucket=handle["bucket"], Key=handle["key"]
        )
        with closing(response["Body"]) as stream:
            yield stream


def copy_bounded(source: Any, destination: Path) -> tuple[str, int]:
    import hashlib

    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with destination.open("xb") as sink:
        destination.chmod(0o600)
        while chunk := source.read(1 << 20):
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise OSError("source exceeds the per-file artifact limit")
            digest.update(chunk)
            sink.write(chunk)
    return digest.hexdigest(), total


def shared_sources(
    conn: Any,
    stores: dict,
    *,
    client_factory: Callable[[str, dict], Any] | None = None,
) -> Iterator[dict]:
    """List shared-file objects, which have no database rows."""
    from yoke_core.domain.shared_file_storage import local_shared_file_root

    for project, store in stores.items():
        root_key = f"shared-files/{project}/"
        if store.get("bucket"):
            prefix = (store.get("prefix") or "").strip("/")
            prefix = f"{prefix}/{root_key}" if prefix else root_key
            client = (client_factory or _client)(project, store)
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=store["bucket"], Prefix=prefix
            ):
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith("/"):
                        continue
                    yield {
                        "key": root_key + obj["Key"][len(prefix) :],
                        "original_handle": s3_handle(store["bucket"], obj["Key"]),
                        "project": project,
                        "bytes": int(obj["Size"]),
                    }
        else:
            root = local_shared_file_root() / project
            if root.is_dir():
                for path in sorted(root.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        yield {
                            "key": root_key + path.relative_to(root).as_posix(),
                            "original_handle": local_handle(str(path)),
                            "project": project,
                            "bytes": path.stat().st_size,
                        }


def write_file(
    path: Path,
    key: str,
    *,
    project: str,
    store: dict,
    content_type: str | None = None,
    client_factory: Callable[[str, dict], Any] | None = None,
) -> dict:
    """Write through captured destination routing, ignoring imported settings."""
    if store.get("bucket"):
        prefix = (store.get("prefix") or "").strip("/")
        destination = f"{prefix}/{key}" if prefix else key
        try:
            with path.open("rb") as stream:
                (client_factory or _client)(project, store).put_object(
                    Bucket=store["bucket"],
                    Key=destination,
                    Body=stream,
                    ContentType=content_type or "application/octet-stream",
                )
        except Exception as exc:
            raise UniverseArchiveError(
                "archive_artifact_write_failed: "
                + safe_aws_error_reason(exc)
                + "; repair destination storage access and retry the import"
            ) from exc
        return s3_handle(store["bucket"], destination, content_type)
    from yoke_core.domain.shared_file_storage import _write_local

    root = machine_config.yoke_home()
    target = root / (
        key
        if key.startswith("shared-files/")
        else "artifacts/" + key.removeprefix("qa-artifacts/")
    )
    try:
        _write_local(target, path.read_bytes())
    except OSError as exc:
        raise UniverseArchiveError(
            "archive_artifact_write_failed: destination disk is unavailable; "
            "repair its permissions or free disk space and retry the import"
        ) from exc
    return local_handle(str(target.resolve()), content_type)


def apply_destination_settings(conn: Any, stores: dict) -> None:
    """Retain destination routing so later artifact reads use the written store."""
    rows = conn.execute(
        "SELECT e.id, p.slug, e.settings FROM environments e "
        "JOIN sites s ON s.id=e.site JOIN projects p ON p.id=s.project_id"
    ).fetchall()
    for project, store in stores.items():
        if conn.execute("SELECT 1 FROM projects WHERE slug=%s", (project,)).fetchone():
            ensure_destination_store(conn, project, store)
    for environment_id, project, raw in rows:
        settings = raw if isinstance(raw, dict) else json_helper.loads_text(raw or "{}")
        store = stores.get(project, {})
        settings.pop("artifacts", None)
        if store.get("bucket"):
            settings["artifacts"] = {k: store[k] for k in ("bucket", "prefix")}
        conn.execute(
            "UPDATE environments SET settings=%s WHERE id=%s",
            (json_helper.dumps_compact(settings), environment_id),
        )


def handle_size(
    handle: dict,
    *,
    project: str,
    store: dict,
    repo_root: str | None = None,
    client_factory: Callable[[str, dict], Any] | None = None,
) -> int:
    if handle["backend"] == "s3":
        return int(
            (client_factory or _client)(project, store).head_object(
                Bucket=handle["bucket"], Key=handle["key"]
            )["ContentLength"]
        )
    path = Path(handle["path"])
    if not path.is_absolute():
        if not repo_root:
            raise OSError("relative source path has no project checkout")
        path = Path(repo_root) / path
    return path.stat().st_size


def ensure_destination_store(conn: Any, project: str, store: dict) -> None:
    """Keep a readable S3 route even when the source had no environments."""
    if not store.get("bucket"):
        return
    project_id = conn.execute(
        "SELECT id FROM projects WHERE slug=%s", (project,)
    ).fetchone()[0]
    exists = conn.execute(
        "SELECT 1 FROM environments WHERE project_id=%s", (project_id,)
    ).fetchone()
    if not exists:
        site = conn.execute(
            "SELECT id FROM sites WHERE project_id=%s ORDER BY id LIMIT 1",
            (project_id,),
        ).fetchone()
        if site is None:
            site = conn.execute(
                "INSERT INTO sites(project_id,name,created_at) VALUES(%s,'default',now()) RETURNING id",
                (project_id,),
            ).fetchone()
        conn.execute(
            "INSERT INTO environments(site,project_id,name,settings,created_at) "
            "VALUES(%s,%s,%s,%s,now())",
            (
                site[0],
                project_id,
                store.get("environment") or "prod",
                json_helper.dumps_compact(
                    {"artifacts": {k: store[k] for k in ("bucket", "prefix")}}
                ),
            ),
        )
    if store.get("region"):
        row = conn.execute(
            "SELECT id, settings FROM project_capabilities "
            "WHERE project_id=%s AND type='aws-admin'",
            (project_id,),
        ).fetchone()
        settings = (
            (
                row[1]
                if isinstance(row[1], dict)
                else json_helper.loads_text(row[1] or "{}")
            )
            if row
            else {}
        )
        settings["region"] = store["region"]
        if row:
            conn.execute(
                "UPDATE project_capabilities SET settings=%s WHERE id=%s",
                (json_helper.dumps_compact(settings), row[0]),
            )
        else:
            conn.execute(
                "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
                "VALUES(%s,'aws-admin',%s,now())",
                (project_id, json_helper.dumps_compact(settings)),
            )
