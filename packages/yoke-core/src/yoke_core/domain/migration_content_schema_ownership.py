"""Owner handoff for project-declared migration-content schema objects."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from yoke_core.domain import db_backend, migration_fleet_ownership
from yoke_core.domain.migration_content_transition_guard import (
    adoption_transition_guard_function_name,
)

if TYPE_CHECKING:
    from yoke_core.domain.migration_content_schema import AdoptionEvidenceContract
    from yoke_core.domain.migration_ledger_contract import LedgerContract


ADOPTION_EVIDENCE_GUARD_PREFIX = "migration_evidence_guard_"


class MigrationContentSchemaOwnershipError(RuntimeError):
    """Prepared schema objects do not belong to the ledger's serving owner."""


def adoption_evidence_guard_object_name(table: str) -> str:
    """Return the collision-resistant evidence-guard object-name stem."""
    digest = hashlib.sha256(table.encode("utf-8")).hexdigest()[:16]
    return f"{ADOPTION_EVIDENCE_GUARD_PREFIX}{digest}"


def migration_content_guard_function_names(
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> tuple[str, str]:
    """Return the exact zero-argument functions declared by the contracts."""
    return (
        f"{adoption_evidence_guard_object_name(evidence.table)}_fn",
        adoption_transition_guard_function_name(ledger, evidence),
    )


def migration_content_schema_owner_is_aligned(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> bool:
    """Return whether every managed object belongs to the ledger owner."""
    if not db_backend.connection_is_postgres(conn):
        return True
    try:
        owner = migration_fleet_ownership.table_owner(conn, ledger.table)
    except RuntimeError:
        return False
    return migration_fleet_ownership.schema_objects_owned_by(
        conn,
        tables=(ledger.table, evidence.table),
        trigger_functions=migration_content_guard_function_names(ledger, evidence),
        owner=owner,
    )


def migration_content_schema_ownership_detail(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str | None:
    """Return a preflight refusal when managed object ownership has drifted."""
    if migration_content_schema_owner_is_aligned(conn, ledger, evidence):
        return None
    return (
        "migration content table or guard-function ownership differs from "
        f"declared ledger {ledger.table!r}"
    )


@contextmanager
def preparation_owner_authority(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> Iterator[None]:
    """Hold ledger-owner authority through convergence and exact handoff."""
    if not db_backend.connection_is_postgres(conn):
        yield
        return

    owner = migration_fleet_ownership.table_owner(conn, ledger.table)
    functions = migration_content_guard_function_names(ledger, evidence)
    with migration_fleet_ownership.owner_transfer_authority(conn, owner=owner):
        yield
        migration_fleet_ownership.realign_trigger_functions(
            conn,
            functions=functions,
            owner=owner,
        )
        migration_fleet_ownership.realign(
            conn,
            tables=(evidence.table,),
            owner=owner,
        )
        if not migration_fleet_ownership.schema_objects_owned_by(
            conn,
            tables=(ledger.table, evidence.table),
            trigger_functions=functions,
            owner=owner,
        ):
            raise MigrationContentSchemaOwnershipError(
                "prepared migration content objects are not owned by "
                f"ledger owner {owner!r}"
            )


__all__ = [
    "ADOPTION_EVIDENCE_GUARD_PREFIX",
    "MigrationContentSchemaOwnershipError",
    "adoption_evidence_guard_object_name",
    "migration_content_guard_function_names",
    "migration_content_schema_owner_is_aligned",
    "migration_content_schema_ownership_detail",
    "preparation_owner_authority",
]
