"""Admit a set of items into a run's membership in the caller's transaction.

:func:`admit_run_items` is the single connection-scoped write every entrance
shares — carried enrollment, takeover, run creation and ``cmd_add_item``:
validated project/flow/stage binding, validated delivery intent, an encoded
requirement selection, and the membership row. Every fact it checks is read
once for the whole set, so admitting thirty members costs the same round
trips as admitting one; the first refusing member, in id order, refuses.

Where no selection was supplied it derives one from the item's outstanding
post-deploy obligations
(:mod:`yoke_core.domain.deployment_member_post_deploy_admission`), so the
silence that used to mean "deliver nothing provable" now means "deliver what
this item still owes".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from typing import Any

from yoke_core.domain.deployment_landing_guard import open_landing_refusals
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.deployment_admission_reads import read_snapshot_inputs
from yoke_core.domain.deployment_item_flow_admission import (
    completion_flow_refusals,
    freeze_item_completion_flows,
)
from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_sets,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    requires_release_admission,
    validate_delivery_intent,
)
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.workflow_delivery_binding_validation import validate_run_member
from yoke_core.domain.workflow_item_binding_validation import (
    has_workflow_pin_schema,
    read_pinned_items,
)


@dataclass(frozen=True)
class MemberAdmission:
    """One item to admit, with its optional explicit intent and selection.

    An empty selection is derived from the item's outstanding obligations.
    """

    item_id: int
    delivery_intent: str | None = None
    requirement_ids: tuple[int, ...] = ()

    @property
    def derived(self) -> bool:
        return not self.requirement_ids


#: Turns one member's refusal into the exception its caller raises instead.
Refusal = Callable[[int, Exception], Exception]


@dataclass(frozen=True)
class RunItemsAdmission:
    """Validated membership rows not yet inserted; see :func:`prepare_run_items`."""

    ids: tuple[int, ...]
    intents: dict[int, str | None]
    selections: dict[int, str | None]
    refs: dict[int, str]
    requirement_ids: tuple[int, ...]


def admit_run_items(
    conn: Any,
    *,
    run_id: str,
    members: Sequence[MemberAdmission],
    refused: Refusal | None = None,
) -> dict[int, str]:
    """Insert one validated membership row per member; return their public refs.

    The caller owns the commit, which is what lets enrollment land inside the
    same transaction that freezes the composition it just completed.

    A membership with nothing selected takes on the item's outstanding
    post-deploy obligations, because a post_deploy row is answered by this
    run's admitted copy and by nothing else: an empty selection would ship
    the code while leaving the obligation unanswerable. An explicit
    selection is a deliberate operator choice and is used verbatim.

    A derived list is validated here but not stored: it answers "what does
    this item still owe", and an obligation minted between this row and the
    composition freeze belongs in it. The column is therefore left null,
    which tells the freeze to derive again. An explicit selection is stored
    as given, and the freeze takes it as given.

    *refused* receives the refusing member and its cause, and returns the
    exception to raise in its place; without it the cause is raised as is.
    """
    admission = prepare_run_items(conn, run_id=run_id, members=members, refused=refused)
    return insert_run_items(conn, run_id, admission)


def insert_run_items(
    conn: Any, run_id: str, admission: RunItemsAdmission
) -> dict[int, str]:
    """Insert the rows :func:`prepare_run_items` validated; return their refs."""
    ids = list(admission.ids)
    if not ids:
        return {}
    added_at = instant_parameter(conn, utc_now())
    conn.execute(
        "INSERT INTO deployment_run_items "
        "(run_id, item_id, added_at, delivery_intent, requirement_selection) "
        "SELECT %s, member.item_id, %s, member.intent, member.selection "
        "FROM unnest(%s::bigint[], %s::text[], %s::text[]) "
        "AS member(item_id, intent, selection)",
        (
            run_id,
            added_at,
            ids,
            [admission.intents[item_id] for item_id in ids],
            [admission.selections[item_id] for item_id in ids],
        ),
    )
    return {item_id: admission.refs[item_id] for item_id in ids}


def prepare_run_items(
    conn: Any,
    *,
    run_id: str,
    members: Sequence[MemberAdmission],
    refused: Refusal | None = None,
    lock_reads: bool = True,
) -> RunItemsAdmission:
    """Validate every member and decide its row, inserting nothing.

    Pins each item's completion flow, as admission always has. With
    ``lock_reads=False`` the requirement and plan rows the selections read
    stay unlocked, for a caller deciding before the run lock; it locks
    ``requirement_ids`` and ``plan_ids`` under the run lock and proves them
    unchanged before :func:`insert_run_items`.
    """
    entries = {int(member.item_id): member for member in members}
    ids = sorted(entries)
    if not ids:
        return RunItemsAdmission((), {}, {}, {}, ())

    def refuse(item_id: int, exc: Exception) -> None:
        if refused is None:
            raise exc
        raise refused(item_id, exc) from exc

    def check(item_id: int, answer: Callable[[], Any]) -> Any:
        try:
            return answer()
        except (LookupError, ValueError) as exc:
            refuse(item_id, exc)

    landing_refusals = open_landing_refusals(conn, ids)
    if landing_refusals:
        first = min(landing_refusals)
        refuse(first, ValueError(landing_refusals[first]))

    pinned = read_pinned_items(conn, ids) if has_workflow_pin_schema(conn) else None
    states = {
        item_id: None
        if pinned is None
        else check(
            item_id,
            lambda: validate_run_member(
                conn,
                run_id=run_id,
                item_id=item_id,
                pinned=pinned.get(item_id),
                attached=False,
            ),
        )
        for item_id in ids
    }
    if requires_release_admission(conn, run_id):
        refusals = completion_flow_refusals(conn, ids)
        first = next((item_id for item_id in ids if item_id in refusals), None)
        if first is not None:
            refuse(first, ValueError(refusals[first]))
    freeze_item_completion_flows(conn, ids)
    intents = {
        item_id: check(
            item_id,
            lambda: validate_delivery_intent(
                entries[item_id].delivery_intent, states[item_id]
            ),
        )
        for item_id in ids
    }
    derived = post_deploy_admission_sets(
        conn,
        run_id=run_id,
        item_ids=[item_id for item_id in ids if entries[item_id].derived],
    )
    selections = {
        item_id: check(
            item_id,
            lambda: requirement_selection(
                requirement_ids=(
                    derived[item_id][0]
                    if item_id in derived
                    else entries[item_id].requirement_ids
                ),
            ),
        )
        for item_id in ids
    }
    admission = read_snapshot_inputs(
        conn,
        item_ids=ids,
        requirement_ids=_selected(entries, derived),
        lock=lock_reads,
    )
    for item_id in ids:
        # Validated now so an unusable obligation refuses here rather than at
        # the freeze, even though a derived list is not what gets stored.
        check(
            item_id,
            lambda: snapshot_member_requirements(
                conn,
                run_id=run_id,
                item_id=item_id,
                selection_json=selections[item_id],
                admission=admission,
            ),
        )
    ref = render_item_ref_lookup(conn, ids)
    return RunItemsAdmission(
        tuple(ids),
        intents,
        {
            item_id: None if item_id in derived else selections[item_id]
            for item_id in ids
        },
        {item_id: ref(item_id) for item_id in ids},
        tuple(sorted(admission.requirements)),
    )


def admit_run_item(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    delivery_intent: str | None = None,
    requirement_ids: Iterable[int] = (),
) -> str:
    """Admit one item; see :func:`admit_run_items`."""
    member = MemberAdmission(int(item_id), delivery_intent, tuple(requirement_ids))
    return admit_run_items(conn, run_id=run_id, members=(member,))[int(item_id)]


def _selected(entries: dict[int, MemberAdmission], derived: dict) -> list[int]:
    values = [value for entry in entries.values() for value in entry.requirement_ids]
    values.extend(value for admitted, _ in derived.values() for value in admitted)
    return values


__all__ = [
    "MemberAdmission",
    "RunItemsAdmission",
    "admit_run_item",
    "admit_run_items",
    "insert_run_items",
    "prepare_run_items",
]
