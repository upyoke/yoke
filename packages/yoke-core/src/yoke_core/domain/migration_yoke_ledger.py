"""Yoke's concrete adapter for the project-neutral migration contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

from yoke_core.domain.migration_artifact_trust import ArtifactVerifier
from yoke_core.domain.migration_content_adoption import (
    AdoptionRecord,
    adopt_legacy_content_identities,
)
from yoke_core.domain.migration_content_schema import (
    AdoptionEvidenceContract,
    adoption_evidence_verifier,
    migration_content_schema_is_prepared,
    prepare_migration_content_schema,
    write_adoption_evidence,
)
from yoke_core.domain.migration_history import MigrationEntry
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    MigrationHistoryManifest,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract, MEMBERSHIP


YOKE_MIGRATION_MODULES_DIR = "packages/yoke-core/src/yoke_core/domain/migrations"
YOKE_LEDGER_TABLE = "applied_migrations"
YOKE_ENTRY_COLUMN = "migration_name"
YOKE_DIGEST_COLUMN = "content_sha256"
YOKE_SERVING_FLOOR_COLUMN = "minimum_serving_version"
YOKE_APPLIED_AT_COLUMN = "applied_at"
YOKE_APPLIED_BY_COLUMN = "applied_by"
YOKE_ADOPTION_EVIDENCE_TABLE = "migration_content_adoptions"
YOKE_RELEASE_ATTESTATION_WORKFLOW = ".github/workflows/yoke-build-artifacts.yml"
YOKE_ADOPTION_EVIDENCE_CONTRACT = AdoptionEvidenceContract(
    table=YOKE_ADOPTION_EVIDENCE_TABLE,
)

YOKE_LEDGER_CONTRACT = LedgerContract(
    table=YOKE_LEDGER_TABLE,
    entry_column=YOKE_ENTRY_COLUMN,
    digest_column=YOKE_DIGEST_COLUMN,
    serving_floor_column=YOKE_SERVING_FLOOR_COLUMN,
    semantics=MEMBERSHIP,
    applied_at_column=YOKE_APPLIED_AT_COLUMN,
    applied_by_column=YOKE_APPLIED_BY_COLUMN,
)


def yoke_ledger_declaration() -> dict[str, str]:
    """Return a fresh JSON-ready declaration of Yoke's concrete ledger."""
    return {
        "table": YOKE_LEDGER_CONTRACT.table,
        "entry_column": YOKE_LEDGER_CONTRACT.entry_column,
        "digest_column": YOKE_LEDGER_CONTRACT.digest_column,
        "semantics": YOKE_LEDGER_CONTRACT.semantics,
        "serving_floor_column": YOKE_LEDGER_CONTRACT.serving_floor_column,
        "applied_at_column": YOKE_LEDGER_CONTRACT.applied_at_column,
        "applied_by_column": YOKE_LEDGER_CONTRACT.applied_by_column,
    }


def governed_yoke_postgres_seed(location: Mapping[str, Any]) -> dict[str, Any]:
    """Build Yoke's own model without making its names generic defaults."""
    from yoke_core.domain.migration_model_capability_defaults import (
        governed_postgres_seed,
    )
    from yoke_core.domain import db_backend

    return governed_postgres_seed(
        location,
        modules_dir=YOKE_MIGRATION_MODULES_DIR,
        ledger=yoke_ledger_declaration(),
        connection_env_var=db_backend.PG_DSN_ENV,
    )


def converge_yoke_migration_content_schema(
    conn: Any,
    *,
    repair_existing_guards: bool = False,
) -> None:
    """Converge Yoke's content schema under the declared guard-repair policy."""
    from yoke_core.domain.migration_content_schema import (
        converge_migration_content_schema,
    )

    converge_migration_content_schema(
        conn,
        YOKE_LEDGER_CONTRACT,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
        repair_existing_guards=repair_existing_guards,
    )


def prepare_yoke_migration_content_schema(conn: Any) -> None:
    """Commit Yoke's additive content schema before candidate boot."""
    prepare_migration_content_schema(
        conn,
        YOKE_LEDGER_CONTRACT,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
    )


def yoke_migration_content_schema_is_prepared(conn: Any) -> bool:
    """Return whether Yoke's digest and evidence schema is ready."""
    return migration_content_schema_is_prepared(
        conn,
        YOKE_LEDGER_CONTRACT,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
    )


def ensure_yoke_migration_ledger(
    conn: Any,
    *,
    repair_existing_guards: bool = False,
) -> None:
    """Create/converge Yoke's ledger under the declared guard-repair policy."""
    from yoke_core.domain.migration_audit_schema import (
        ensure_migration_ledger_table,
    )

    ensure_migration_ledger_table(
        conn,
        YOKE_LEDGER_CONTRACT,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
        repair_existing_guards=repair_existing_guards,
    )


def write_yoke_adoption_evidence(
    conn: Any,
    records: Tuple[AdoptionRecord, ...],
) -> None:
    """Append adoption evidence inside the caller's open transaction."""
    write_adoption_evidence(
        conn,
        records,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
    )


def adopt_yoke_legacy_content_identities(
    conn: Any,
    *,
    history: Sequence[MigrationEntry],
    manifest: MigrationHistoryManifest,
    artifact: ArtifactIdentity,
    expected_manifest_sha256: str,
    artifact_verifier: ArtifactVerifier | None,
    adopted_by: str,
    entry_names: Sequence[str] | None = None,
    adopted_at: str | None = None,
) -> Tuple[AdoptionRecord, ...]:
    """Use the generic adopter with Yoke's ledger and evidence table."""
    from yoke_core.domain import db_backend, migration_fleet_ownership

    authority = None
    if db_backend.connection_is_postgres(conn):

        def yoke_owner_authority():
            return migration_fleet_ownership.owner_transfer_authority(
                conn,
                owner=migration_fleet_ownership.table_owner(
                    conn, YOKE_LEDGER_CONTRACT.table
                ),
            )

        authority = yoke_owner_authority
    return adopt_legacy_content_identities(
        conn,
        history=history,
        ledger=YOKE_LEDGER_CONTRACT,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_verifier=artifact_verifier,
        adopted_by=adopted_by,
        write_evidence=write_yoke_adoption_evidence,
        verify_evidence_immutability=adoption_evidence_verifier(
            YOKE_LEDGER_CONTRACT, YOKE_ADOPTION_EVIDENCE_CONTRACT
        ),
        transaction_authority=authority,
        entry_names=entry_names,
        adopted_at=adopted_at,
    )


__all__ = [
    "YOKE_ADOPTION_EVIDENCE_TABLE",
    "YOKE_ADOPTION_EVIDENCE_CONTRACT",
    "YOKE_APPLIED_AT_COLUMN",
    "YOKE_APPLIED_BY_COLUMN",
    "YOKE_DIGEST_COLUMN",
    "YOKE_ENTRY_COLUMN",
    "YOKE_LEDGER_CONTRACT",
    "YOKE_LEDGER_TABLE",
    "YOKE_MIGRATION_MODULES_DIR",
    "YOKE_RELEASE_ATTESTATION_WORKFLOW",
    "YOKE_SERVING_FLOOR_COLUMN",
    "adopt_yoke_legacy_content_identities",
    "converge_yoke_migration_content_schema",
    "ensure_yoke_migration_ledger",
    "governed_yoke_postgres_seed",
    "prepare_yoke_migration_content_schema",
    "write_yoke_adoption_evidence",
    "yoke_migration_content_schema_is_prepared",
    "yoke_ledger_declaration",
]
