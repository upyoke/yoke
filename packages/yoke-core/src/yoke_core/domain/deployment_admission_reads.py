"""Fresh QA inputs for one enrollment, discarded before another composition.

The caller holds item workflow bindings and the run row. Requirements are
locked here in ID order, using the same projections as individual
admission. A caller reading before the run lock reads them unlocked, then
locks the same rows under the run lock before proving them unchanged. These values never enter the immutable repository-read cache or
the unlocked Shipping presentation cache.
"""

from dataclasses import dataclass

from yoke_contracts.public_ref import ITEM_NOT_FOUND
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_requirement_snapshot_format import REQUIREMENT_FIELDS
from yoke_core.domain.qa_obligation_settlement import requirement_retracted_at_select
from yoke_core.domain.schema_common import _table_exists


@dataclass
class AdmissionReads:
    requirements: dict
    projects: dict

    def project_id(self, item_id):
        if item_id not in self.projects:
            raise LookupError(ITEM_NOT_FOUND)
        return self.projects[item_id]


def read_snapshot_inputs(conn, *, item_ids, requirement_ids, lock=True):
    """Read mutable facts once inside the caller's current transaction.

    ``lock=False`` reads the same facts without holding the requirement
    rows, for a read taken before the run lock; its caller locks them
    under the run lock and proves them unchanged before writing.
    """
    items = tuple(sorted(set(int(value) for value in item_ids)))
    selected = tuple(sorted(set(int(value) for value in requirement_ids)))
    if not items:
        return AdmissionReads({}, {})
    postgres = db_backend.connection_is_postgres(conn)
    marker = "%s" if postgres else "?"
    lock_rows = lock and postgres
    suffix = " FOR UPDATE" if lock_rows else ""
    requirements = {}
    if selected:
        if not _table_exists(conn, "qa_requirements"):
            raise LookupError("QA requirement catalog is not installed")
        rows = query_rows(
            conn,
            f"SELECT {','.join(REQUIREMENT_FIELDS)},"
            f"waived_at,{requirement_retracted_at_select(conn)} FROM qa_requirements "
            f"WHERE id IN ({','.join(marker for _ in selected)}) ORDER BY id{suffix}",
            selected,
        )
        requirements = {int(row["id"]): row for row in rows}
    markers = ",".join(marker for _ in items)
    projects = {
        int(row["id"]): int(row["project_id"])
        for row in query_rows(
            conn,
            f"SELECT id,project_id FROM items WHERE id IN ({markers})",
            items,
        )
    }
    return AdmissionReads(requirements, projects)
