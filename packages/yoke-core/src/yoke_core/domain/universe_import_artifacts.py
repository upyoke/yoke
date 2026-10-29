"""Move imported evidence handles to a destination tenant's object namespace."""

from typing import Any

from yoke_contracts.shared_files import SHARED_FILES_STORAGE_KIND
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.qa_artifact_handle import (
    QA_ARTIFACT_STORAGE_KIND,
    parse_handle,
    safe_segment,
    serialize_handle,
)


class UniverseImportArtifactError(ValueError):
    """An import cannot safely map its copied object references."""

    code = "import_artifact_namespace_invalid"


def rewrite_imported_artifacts(
    conn: Any,
    *,
    source_bucket: str,
    source_tenant_id: str,
    destination_bucket: str,
    destination_tenant_id: str,
) -> dict[str, str]:
    """Rewrite stored handles and return the exact S3 sync prefix map.

    Shared files have no database row: include their prefix even when there
    are no QA artifacts. Copy bytes with this map before serving the import.
    The caller owns commit; a refusal undoes only this function's writes.
    """
    try:
        source_bucket = safe_segment(source_bucket)
        destination_bucket = safe_segment(destination_bucket)
        source_prefix = f"tenants/{safe_segment(source_tenant_id)}/"
        destination_prefix = f"tenants/{safe_segment(destination_tenant_id)}/"
    except ValueError as exc:
        raise UniverseImportArtifactError(
            "import_artifact_namespace_invalid: provide explicit safe bucket "
            "and tenant identifiers, then retry the import"
        ) from exc
    kinds = (QA_ARTIFACT_STORAGE_KIND, SHARED_FILES_STORAGE_KIND)
    mapping = {
        f"s3://{source_bucket}/{source_prefix}{kind}/": f"s3://{destination_bucket}/{destination_prefix}{kind}/"
        for kind in kinds
    }
    with savepoint(conn, "imported_artifacts", owns=False):
        rows = conn.execute(
            "SELECT id, artifact_handle FROM qa_artifacts "
            "WHERE artifact_handle IS NOT NULL ORDER BY id FOR UPDATE"
        ).fetchall()
        for artifact_id, raw in rows:
            try:
                handle = parse_handle(raw)
                key = str(handle.get("key") or "")
                relative = key.removeprefix(source_prefix)
                if (
                    handle["backend"] != "s3"
                    or handle["bucket"] != source_bucket
                    or not key.startswith(source_prefix)
                    or relative.split("/", 1)[0] not in kinds
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                ):
                    raise ValueError("handle is outside the source namespace")
            except ValueError as exc:
                raise UniverseImportArtifactError(
                    f"import_artifact_namespace_invalid: artifact {artifact_id} "
                    "cannot be copied with the supplied source prefix; rehome "
                    "its evidence into the source tenant's bucket and export again"
                ) from exc
            handle.update(bucket=destination_bucket, key=destination_prefix + relative)
            conn.execute(
                "UPDATE qa_artifacts SET artifact_handle=%s WHERE id=%s",
                (serialize_handle(handle), artifact_id),
            )
    return mapping


__all__ = ["UniverseImportArtifactError", "rewrite_imported_artifacts"]
