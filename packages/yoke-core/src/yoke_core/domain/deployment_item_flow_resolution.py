"""Resolve an item's project and effective delivery flow."""

from typing import Any, Iterable, NamedTuple

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain import workflow_project_defaults
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.deployment_flow_succession import succession_chains
from yoke_core.domain.project_identity import render_item_ref, resolve_project
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_project_defaults import WorkflowProjectDefaultError

NO_FLOW_HEAD = "has no deployment_flow; cannot start deploy run"

FLOW_SOURCE_ITEM = "item"
FLOW_SOURCE_PROJECT_DEFAULT = "project_default"
FLOW_SOURCE_NONE = "none"
FLOW_SOURCE_UNREADABLE = "unreadable"


class ItemCompletionFlowFact(NamedTuple):
    """The closing flow for one item, and whether it is stored or inherited.

    ``pinned`` is the item's stored pin when completion follows that pin's
    active successor instead; it is empty when ``flow`` is the pin itself.
    ``superseded`` is the pin and every flow between it and ``flow``.
    """

    flow: str
    source: str
    pinned: str = ""
    superseded: tuple[str, ...] = ()

    @property
    def closing_flows(self) -> frozenset[str]:
        """Every flow whose run is completion authority for the item."""
        return frozenset((self.flow, *self.superseded)) if self.flow else frozenset()


def item_completion_flow_facts(
    conn: Any,
    item_ids: Iterable[int],
) -> dict[int, ItemCompletionFlowFact]:
    """The closing flow and where it came from, keyed by internal id.

    Same batching as :func:`item_completion_flows`: one item-row read, and
    one default resolution per distinct project-and-workflow pair. A default
    that cannot be read is ``source='unreadable'`` with an empty flow, never
    silently the same as a project that declared none.

    A stored pin whose flow was retired resolves to its newest active
    successor (see :mod:`deployment_flow_succession`); the pin stays stored
    and is reported beside the flow that now closes the item.
    """
    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not ids or not _column_exists(conn, "items", "deployment_flow"):
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    has_workflow = _column_exists(conn, "items", "workflow_id")
    columns = "i.id, i.deployment_flow, p.slug"
    if has_workflow:
        columns += ", i.workflow_id"
    rows = conn.execute(
        f"SELECT {columns} "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id IN ({','.join(marker for _ in ids)})",
        ids,
    ).fetchall()
    facts: dict[int, ItemCompletionFlowFact] = {}
    unresolved: dict[int, tuple[str, str]] = {}
    pins: dict[int, str] = {}
    for raw in rows:
        row = dict(raw)
        item_id = int(row["id"])
        pinned = str(row["deployment_flow"] or "").strip()
        if pinned:
            pins[item_id] = pinned
            continue
        facts[item_id] = ItemCompletionFlowFact("", FLOW_SOURCE_NONE)
        if not has_workflow:
            continue
        project = str(row["slug"] or "")
        workflow_id = str(row["workflow_id"] or "")
        if project and workflow_id:
            unresolved[item_id] = (project, workflow_id)
    chains = succession_chains(conn, pins.values())
    for item_id, pinned in pins.items():
        chain = chains.get(pinned, (pinned,))
        facts[item_id] = ItemCompletionFlowFact(
            chain[-1],
            FLOW_SOURCE_ITEM,
            pinned if len(chain) > 1 else "",
            chain[:-1],
        )
    if not unresolved:
        return facts
    if not _table_exists(conn, "project_structure"):
        unreadable = ItemCompletionFlowFact("", FLOW_SOURCE_UNREADABLE)
        for item_id in unresolved:
            facts[item_id] = unreadable
        return facts
    defaults: dict[tuple[str, str], ItemCompletionFlowFact] = {}
    for item_id, key in unresolved.items():
        if key not in defaults:
            try:
                resolved = workflow_project_defaults.get_delivery_default(
                    conn,
                    project=key[0],
                    workflow_id=key[1],
                )
            except WorkflowProjectDefaultError:
                defaults[key] = ItemCompletionFlowFact(
                    "",
                    FLOW_SOURCE_UNREADABLE,
                )
            else:
                flow = str(resolved or "")
                defaults[key] = ItemCompletionFlowFact(
                    flow,
                    FLOW_SOURCE_PROJECT_DEFAULT if flow else FLOW_SOURCE_NONE,
                )
        facts[item_id] = defaults[key]
    return facts


def item_completion_flows(conn: Any, item_ids: Iterable[int]) -> dict[int, str]:
    """The closing flow for a whole set of items, keyed by internal id.

    The set form exists because the callers that need this need it for every
    item on a page. Asking per item re-probed the schema and re-resolved the
    same project default once per row; here the schema question is asked
    once, the item rows come back in one statement, and a project default is
    resolved once per distinct project-and-workflow pair.

    An item with no closing flow maps to ``""``, the same answer
    :func:`item_completion_flow` gives. An unreadable default is also
    ``""`` here — callers that need to tell that apart from a declared-none
    use :func:`item_completion_flow_facts`.
    """
    return {
        item_id: fact.flow
        for item_id, fact in item_completion_flow_facts(conn, item_ids).items()
    }


def item_completion_flow(conn: Any, item_id: int) -> str:
    """The flow that may close this item: explicit pin, else project default.

    A pin to a retired flow resolves to its newest active successor.

    Membership can carry the item on another same-project run. Completion,
    QA source obligations, and done-transition evidence all key off this
    flow — never the newest carrying run of any flow.

    The one-element case of :func:`item_completion_flows`; a caller resolving
    a set of items uses that entry point instead.
    """
    return item_completion_flows(conn, (int(item_id),)).get(int(item_id), "")


def item_closing_flows(conn: Any, item_id: int) -> frozenset[str]:
    """The completion flow plus every retired flow its pin followed to it:
    a delivery on the pin or an intermediate successor still closes it."""
    fact = item_completion_flow_facts(conn, (int(item_id),)).get(int(item_id))
    return fact.closing_flows if fact else frozenset()


def completion_flow_refusal(conn: Any, item_id: int) -> str:
    """Explain why a delivery-ready item cannot enter a release composition."""
    fact = item_completion_flow_facts(conn, (int(item_id),)).get(int(item_id))
    if fact and fact.flow:
        return ""
    ref = render_item_ref(conn, int(item_id))
    if fact and fact.source == FLOW_SOURCE_UNREADABLE:
        return (
            f"{ref} completion flow is unreadable; repair its project workflow "
            "delivery default, then retry the deployment start"
        )
    if not _column_exists(conn, "items", "workflow_id"):
        return (
            f"{ref} completion flow cannot be resolved because items.workflow_id "
            "has not converged; converge the item schema, then retry the "
            "deployment start"
        )
    row = conn.execute(
        "SELECT p.slug,i.workflow_id FROM items i JOIN projects p "
        "ON p.id=i.project_id WHERE i.id=%s",
        (int(item_id),),
    ).fetchone()
    project, workflow = str(row[0]), str(row[1])
    return (
        f"{ref} has no resolvable completion flow; select one with "
        f"yoke workflows delivery-default set --project {project} "
        f"--workflow {workflow} --flow FLOW, then retry the deployment start"
    )


def membership_closes_item(
    *,
    run_flow: str,
    closing_flows: Iterable[str],
    run_project_id: int,
    item_project_id: int,
    source_sha: str,
) -> bool:
    """Whether a membership on this run is completion authority for the item.

    Two memberships are. A run of one of the item's closing flows (its
    completion flow, or a retired flow its pin followed there), and a run
    of another project that recorded a commit for the item's project — that
    carrier resolved this project's source, so it delivers the item's merge
    as surely as the item's own flow would. A same-project run of any other
    flow is not, whatever its candidate happens to contain.

    Pure on purpose: the done-transition evidence read and the attach-time
    coverage notice both ask this, and two copies of it is how one of them
    ends up right and the other quietly wrong.
    """
    closing = frozenset(closing_flows)
    if not closing:
        return False
    if run_flow in closing:
        return True
    return int(run_project_id) != int(item_project_id) and bool(source_sha)


def freeze_item_completion_flow(conn: Any, item_id: int) -> str:
    """Pin the live default onto the item if it has no explicit flow.

    Membership is the last write before a run can ship the item, so the
    default that would close it is frozen here. A later project-default
    change cannot retarget completion authority for an already-admitted
    item.
    """
    if not _column_exists(conn, "items", "deployment_flow"):
        return ""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT deployment_flow FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    pinned = str(
        (row["deployment_flow"] if hasattr(row, "keys") else row[0]) or ""
    ).strip()
    if pinned:
        return pinned
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return ""
    conn.execute(
        f"UPDATE items SET deployment_flow = {marker} "
        f"WHERE id = {marker} AND COALESCE(deployment_flow, '') = ''",
        (flow, int(item_id)),
    )
    return flow


def lookup_item_project_and_flow(item_id: int) -> tuple:
    """Return project and the flow a new run for this item should use.

    An item pin resolves through its retired flow's active successor; an
    unpinned item uses its workflow delivery default.
    """
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT p.slug AS project, i.deployment_flow, i.workflow_id "
            "FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return None, None
        if pinned := str(row[1] or "").strip():
            return row[0], succession_chains(conn, [pinned])[pinned][-1]
        if row[0] and row[2]:
            return row[0], workflow_project_defaults.get_delivery_default(
                conn,
                project=str(row[0]),
                workflow_id=str(row[2]),
            )
    finally:
        conn.close()
    return row[0], row[1]


def _selectable_flow_ids(conn, project_id: int) -> list:
    """Return the active flow ids this project can still deploy through."""
    rows = conn.execute(
        "SELECT id FROM deployment_flows "
        "WHERE project_id = %s AND status = %s ORDER BY id",
        (project_id, FLOW_STATUS_ACTIVE),
    ).fetchall()
    return [str(row[0]) for row in rows]


def describe_missing_flow(item_ref: str, project: str) -> str:
    """Explain an unresolved delivery flow and name the way out of it.

    A run is attempted long after the filing that left the flow unset, so
    the refusal carries what it takes to get past it rather than only the
    fact that it stopped. The caller passes the item's already-rendered
    reference; this read is about the project's flows, not identity.
    """
    head = f"{item_ref} {NO_FLOW_HEAD}"
    conn = db_helpers.connect()
    try:
        identity = resolve_project(conn, project, required=False)
        flows = _selectable_flow_ids(conn, identity.id) if identity else []
    except LookupError:
        return head
    finally:
        conn.close()
    if identity is None:
        return f"{head}: project {project!r} does not exist."
    if not flows:
        return (
            f"{head}: project {project!r} declares no delivery default for "
            "this item and has no active deployment flow to select. Declare "
            "a flow for the project, then set it as the workflow's delivery "
            "default or pass --flow."
        )
    return (
        f"{head}: project {project!r} declares no delivery default for this "
        f"item. Pass --flow with one of: {', '.join(flows)}."
    )


__all__ = [
    "FLOW_SOURCE_ITEM",
    "FLOW_SOURCE_NONE",
    "FLOW_SOURCE_PROJECT_DEFAULT",
    "FLOW_SOURCE_UNREADABLE",
    "completion_flow_refusal",
    "ItemCompletionFlowFact",
    "NO_FLOW_HEAD",
    "describe_missing_flow",
    "freeze_item_completion_flow",
    "item_completion_flow",
    "item_completion_flow_facts",
    "item_closing_flows",
    "item_completion_flows",
    "lookup_item_project_and_flow",
    "membership_closes_item",
]
