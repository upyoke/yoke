"""Whether an admitted deployment-stage QA copy still matches its source row.

Admission (:mod:`deployment_qa_admission_materialization`) answers a member's
post-deploy obligation by copying the item requirement's body onto a new row
bound to the run, stage and execution target. The copy records where it came
from in ``plan_case_key`` -- ``admitted-requirement-<source id>`` -- and that
key is the only link there is, or needs to be.

Nothing read that link in the amend direction, so a correction to the source
landed on the source alone. The stage kept executing the body frozen at
admission, and the run recorded the resulting failures as product defects
rather than as a case whose author had already retracted it.

This module supplies the comparison both halves of the fix need: the amend
path uses it to decide whether it can reach the copy, and the execution path
uses it to refuse rather than certify a superseded definition.

It digests only the fields that decide what a case *executes*. ``target_env``,
``qa_phase`` and ``qa_kind`` are deliberately excluded: admission rewrites
those to the stage's own target on purpose, so they differ on every healthy
copy and are drift in neither direction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.deployment_qa_admission_materialization import (
    ADMITTED_REQUIREMENT_CASE_PREFIX,
)
from yoke_core.domain.qa_plan_execution_store import canonical, marker
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_FIELD,
    canonical_method_config,
)

#: Columns whose value decides what the case does when it runs. A copy that
#: matches its source across all of them executes the item's current
#: definition, whatever else the two rows disagree about.
DEFINITION_COLUMNS: tuple[str, ...] = (
    "method_id",
    "method_name",
    "runner_id",
    "verdict_path",
    "instructions",
    "expected_outcome",
    "entry_surface",
    "required_completion",
    "host_baseline",
    "suite_id",
    "success_policy",
    "capability_requirements",
    "blocking_mode",
    METHOD_CONFIG_FIELD,
)

STALE_ADMITTED_CASE_CODE = "admitted_case_superseded"

#: Recovery when re-applying the amendment would actually reach the copy.
#: The abort comes first because a live roster is what blocks the write.
REACHABLE_FIELD_RECOVERY = (
    "Abort the stage execution with `yoke qa plan abort`, re-apply the "
    "amendment -- which then reaches the admitted copy -- and start the "
    "stage again."
)

#: Recovery for a copy that CANNOT be corrected, by any path. Telling an
#: operator to refresh it would teach an action nobody can take: the
#: requirement update allowlist does not carry these fields, and
#: `yoke qa plan rematerialize` rewrites the source row rather than a run's
#: plan-less admitted copy. So the honest answer names the three remedies
#: that do exist rather than one that does not.
UNREACHABLE_FIELD_RECOVERY = (
    "{fields} cannot be written on a requirement at all -- the updatable "
    "fields are {allowed}, and `yoke qa plan rematerialize` refreshes the "
    "source row, not a run's plan-less admitted copy. Refreshing this copy "
    "is therefore not an available remedy, and it will certify against the "
    "superseded body for as long as it exists. Take one that is available: "
    "record a corrected case bound to this same run, stage, member and "
    "execution target and supersede this one (`yoke qa requirement supersede "
    "--requirement-id {copy_id} --superseded-by-requirement-id <corrected-id> "
    "--rationale '<why>'`); waive this copy through the registered waiver "
    "surface with explicit authorization; or deliver the item on a new run, "
    "whose admission freezes the corrected body."
)

#: Recovery for a copy that has already answered. Its acceptance snapshot is
#: frozen whatever the field was, so re-applying can never reach it.
ANSWERED_COPY_RECOVERY = (
    "Record a corrected case in its place: `yoke qa requirement supersede "
    "--requirement-id {copy_id} --superseded-by-requirement-id <corrected-id> "
    "--rationale '<why>'`"
)


def reachable_in_place_fields() -> frozenset[str]:
    """Definition fields an in-place requirement write can still reach.

    Imported at call time because :mod:`qa_requirement_config_update` reaches
    this module through the reconciliation path; a module-level import would
    close that cycle. The allowlist stays its owner's rather than becoming a
    second copy here, so a field added there is reachable here in the same
    change.
    """
    from yoke_core.domain.qa_requirement_config_update import (
        UPDATABLE_REQUIREMENT_FIELDS,
    )

    return frozenset(DEFINITION_COLUMNS) & frozenset(UPDATABLE_REQUIREMENT_FIELDS)


class StaleAdmittedCaseError(ValueError):
    """An admitted copy no longer matches its source; the message names why."""


@dataclass(frozen=True)
class AdmittedCaseDivergence:
    """An admitted copy whose body no longer matches its live source row."""

    requirement_id: int
    source_requirement_id: int
    fields: tuple[str, ...]

    def message(self) -> str:
        """The named refusal, with the fields that moved and a real recovery.

        Which recovery is true depends on what moved. Only a field the
        requirement update allowlist carries can be written onto the copy at
        all, so a divergence in any other field has no refresh route and the
        refusal says so instead of promising one.
        """
        reachable = reachable_in_place_fields()
        unreachable = tuple(
            field for field in self.fields if field not in reachable
        )
        if unreachable:
            recovery = UNREACHABLE_FIELD_RECOVERY.format(
                fields=", ".join(unreachable),
                allowed=", ".join(sorted(reachable)),
                copy_id=self.requirement_id,
            )
        else:
            recovery = REACHABLE_FIELD_RECOVERY
        return (
            f"{STALE_ADMITTED_CASE_CODE}: admitted QA case "
            f"{self.requirement_id} was copied from item requirement "
            f"{self.source_requirement_id}, which has since been amended "
            f"({', '.join(self.fields)}). Running it would certify against a "
            "definition the item has already superseded. " + recovery
        )


def admitted_source_requirement_id(case_key: Any) -> int | None:
    """The source requirement an admitted case key names, or ``None``.

    Every other case key -- a plan's own, or the ``ad-hoc-`` form -- names no
    source row, so it has nothing to be stale against.
    """
    key = str(case_key or "")
    if not key.startswith(ADMITTED_REQUIREMENT_CASE_PREFIX):
        return None
    tail = key[len(ADMITTED_REQUIREMENT_CASE_PREFIX) :]
    if not tail.isdigit():
        return None
    source_id = int(tail)
    return source_id if source_id > 0 else None


def _comparable(value: Any) -> str:
    """One stable string per stored value, across both rows' storage shapes.

    A column stored as JSON on one row and as an equivalent object on the
    other is the same definition, so both are canonicalised before comparison
    rather than compared as text.
    """
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        return canonical(parsed)
    return canonical(value)


def definition_snapshot(row: Any) -> dict[str, str]:
    """The executable definition of one requirement row, field by field."""
    snapshot: dict[str, str] = {}
    for column in DEFINITION_COLUMNS:
        value = row[column] if hasattr(row, "keys") else None
        if column == METHOD_CONFIG_FIELD:
            snapshot[column] = canonical_method_config(value)
        else:
            snapshot[column] = _comparable(value)
    return snapshot


def _definition_row(conn: Any, requirement_id: int) -> Any:
    columns = ",".join(DEFINITION_COLUMNS)
    return query_one(
        conn,
        f"SELECT id,plan_case_key,{columns} FROM qa_requirements "
        f"WHERE id={marker(conn)}",
        (int(requirement_id),),
    )


def diverging_fields(copy_row: Any, source_row: Any) -> tuple[str, ...]:
    """Which executable fields the copy and its source no longer agree on."""
    copied = definition_snapshot(copy_row)
    live = definition_snapshot(source_row)
    return tuple(
        column for column in DEFINITION_COLUMNS if copied[column] != live[column]
    )


def admitted_case_divergence(
    conn: Any, requirement_id: int
) -> AdmittedCaseDivergence | None:
    """How this case differs from the row it was admitted from, if at all.

    ``None`` covers every case that cannot be stale: one that is not an
    admitted copy, and one whose source row no longer exists -- a deleted
    source supersedes nothing, and the copy remains the run's own record.
    """
    copy_row = _definition_row(conn, int(requirement_id))
    if copy_row is None:
        return None
    source_id = admitted_source_requirement_id(copy_row["plan_case_key"])
    if source_id is None:
        return None
    source_row = _definition_row(conn, source_id)
    if source_row is None:
        return None
    fields = diverging_fields(copy_row, source_row)
    if not fields:
        return None
    return AdmittedCaseDivergence(
        requirement_id=int(requirement_id),
        source_requirement_id=source_id,
        fields=fields,
    )


def require_current_admitted_case(conn: Any, requirement_id: int) -> None:
    """Raise the named refusal when this case's source has moved under it."""
    divergence = admitted_case_divergence(conn, int(requirement_id))
    if divergence is not None:
        raise StaleAdmittedCaseError(divergence.message())


def annotate_admitted_currency(
    conn: Any, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mark every admitted copy in *rows* current or stale against its source.

    This is what makes a running case identifiable without reading two rows
    side by side: a reader listing a deployment run's cases is told which
    definition each one will certify against, and which fields moved when
    that is no longer the item's own.
    """
    for row in rows:
        source_id = admitted_source_requirement_id(row.get("plan_case_key"))
        if source_id is None:
            continue
        divergence = admitted_case_divergence(conn, int(row["id"]))
        row["source_requirement_id"] = source_id
        row["source_currency"] = "stale" if divergence else "current"
        row["source_diverging_fields"] = (
            list(divergence.fields) if divergence is not None else []
        )
    return rows


__all__ = [
    "ANSWERED_COPY_RECOVERY",
    "AdmittedCaseDivergence",
    "DEFINITION_COLUMNS",
    "REACHABLE_FIELD_RECOVERY",
    "STALE_ADMITTED_CASE_CODE",
    "StaleAdmittedCaseError",
    "UNREACHABLE_FIELD_RECOVERY",
    "admitted_case_divergence",
    "admitted_source_requirement_id",
    "annotate_admitted_currency",
    "definition_snapshot",
    "diverging_fields",
    "reachable_in_place_fields",
    "require_current_admitted_case",
]
