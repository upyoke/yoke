"""Fresh QA inputs for one enrollment, discarded before another composition.

The caller holds item workflow bindings and the run row. Requirements and
plans are locked here in ID order, using the same projections as individual
admission. A caller reading before the run lock reads them unlocked, then
locks the same rows under the run lock before proving them unchanged. These values never enter the immutable repository-read cache or
the unlocked Shipping presentation cache.
"""

from dataclasses import dataclass

from yoke_contracts.public_ref import ITEM_NOT_FOUND
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_shared_plan_reads import read_plan_rows
from yoke_core.domain.deployment_requirement_snapshot_format import REQUIREMENT_FIELDS
from yoke_core.domain.qa_obligation_settlement import requirement_retracted_at_select
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql
from yoke_core.domain.schema_common import _table_exists


@dataclass
class AdmissionReads:
    requirements: dict
    projects: dict
    attachments: dict
    plans: dict

    def withdrawn_plans(self, item_id):
        return {
            int(row["plan_id"])
            for row in self.attachments.get(item_id, ())
            if row["qa_phase"] == "post_deploy" and not row["live"]
        }

    def attached_plans(self, item_id):
        return {
            int(row["plan_id"])
            for row in self.attachments.get(item_id, ())
            if row["qa_phase"] == "post_deploy" and row["live"] and row["active"]
        }

    def attachment(self, item_id, plan_id):
        return next(
            (
                row
                for row in self.attachments.get(item_id, ())
                if int(row["plan_id"]) == plan_id and row["live"]
            ),
            None,
        )

    def project_id(self, item_id):
        if item_id not in self.projects:
            raise LookupError(ITEM_NOT_FOUND)
        return self.projects[item_id]


def read_snapshot_inputs(conn, *, item_ids, requirement_ids, plan_ids=(), lock=True):
    """Read mutable facts once inside the caller's current transaction.

    ``lock=False`` reads the same facts without holding the requirement and
    plan rows, for a read taken before the run lock; its caller locks them
    under the run lock and proves them unchanged before writing.
    """
    items = tuple(sorted(set(int(value) for value in item_ids)))
    selected = tuple(sorted(set(int(value) for value in requirement_ids)))
    if not items:
        return AdmissionReads({}, {}, {}, {})
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
    attachments = {}
    if _table_exists(conn, "qa_plan_item_attachments"):
        for row in query_rows(
            conn,
            "SELECT a.item_id,a.plan_id,a.transition_id,a.qa_phase,"
            f"({live_item_attachment_sql(conn, 'a')}) AS live,"
            "(p.id IS NOT NULL AND p.retired_at IS NULL) AS active "
            "FROM qa_plan_item_attachments a LEFT JOIN qa_plans p ON p.id=a.plan_id "
            f"WHERE a.item_id IN ({markers}) ORDER BY a.item_id,a.plan_id",
            items,
        ):
            attachments.setdefault(int(row["item_id"]), []).append(row)
    facts = AdmissionReads(requirements, projects, attachments, {})
    plans = set(plan_ids)
    for item_id in items:
        withdrawn = facts.withdrawn_plans(item_id)
        plans.update(facts.attached_plans(item_id) - withdrawn)
        plans.update(
            int(row["plan_id"])
            for row in requirements.values()
            if row.get("plan_id") is not None
            and int(row.get("item_id") or 0) == item_id
            and row.get("retracted_at") is None
            and int(row["plan_id"]) not in withdrawn
        )
    facts.plans = read_plan_rows(conn, plans, lock_plan=lock_rows)
    return facts
