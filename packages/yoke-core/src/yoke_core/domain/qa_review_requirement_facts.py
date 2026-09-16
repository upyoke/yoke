"""Resolve the project, naming, and subject facts one QA review decision needs.

A requirement reaches review from any of three homes -- a plan case, an item or
epic, or a deployment run -- and the decision surface needs the same facts from
all three: which project's roster may answer, and what to call the thing being
reviewed. Without a project there is no authority to address, so an
unattributable requirement refuses rather than producing an unanswerable ask.

Which home a requirement came from is itself a fact the reviewer needs, because
the three ask different questions. Reviewing an item's verification decides
whether that item's branch is sound; reviewing a deployment run's post-release
check decides what to record about a release that has already happened. A
surface that cannot tell them apart offers to block a release it cannot stop.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.json_helper import loads_text


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def frozen_target_facts(execution_target_json: Any) -> dict[str, Any]:
    """The deployment facts a requirement froze at materialization.

    A release check's environment and candidate are not on the requirement's
    own columns — a run preview has no registered environment row to name in
    ``target_env``, and the candidate belongs to the run. Both are already
    recorded on the execution target the check was materialized against,
    which is the same document the gate judges against. Reading them there
    reports what was actually checked; reading the project's current
    environment instead would report what is true now, which is not the same
    claim and is exactly what a frozen target exists to prevent.
    """
    try:
        target = loads_text(execution_target_json or "") or {}
    except ValueError:
        target = {}
    if not isinstance(target, dict):
        target = {}
    environment = target.get("environment")
    deployment = target.get("deployment")
    return {
        "execution_environment": (
            environment.get("name") if isinstance(environment, dict) else None
        )
        or None,
        "execution_candidate_revision": (
            deployment.get("release_lineage") if isinstance(deployment, dict) else None
        )
        or None,
        "execution_observed_url": target.get("observed_url") or None,
    }


def _apply_frozen_target(value: dict[str, Any]) -> None:
    facts = frozen_target_facts(value.get("execution_target_json"))
    if not value.get("target_env"):
        value["target_env"] = facts["execution_environment"]
    value["candidate_revision"] = facts["execution_candidate_revision"]
    value["observed_url"] = facts["execution_observed_url"]


def requirement_facts(conn: Any, requirement_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id, item_id, epic_id, deployment_run_id, "
        "deployment_member_item_id, plan_id, "
        "plan_case_key, method_id, method_name, expected_outcome, qa_kind, "
        "qa_phase, target_env, success_policy, execution_target_json "
        "FROM qa_requirements "
        f"WHERE id = {p}",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"QA requirement {requirement_id} does not exist")
    value = {key: row[key] for key in row.keys()}
    _apply_frozen_target(value)
    if value.get("plan_id") is not None:
        project = conn.execute(
            f"SELECT project_id, name FROM qa_plans WHERE id = {p}",
            (int(value["plan_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
            value["plan_name"] = str(project[1])
    if (
        value.get("method_id") is not None
        and value.get("method_name") is None
        and value.get("plan_id") is None
    ):
        method = conn.execute(
            f"SELECT name FROM qa_methods WHERE id = {p}",
            (str(value["method_id"]),),
        ).fetchone()
        if method is not None:
            value["method_name"] = str(method[0])
    # A release's per-member check names its item in its own column rather
    # than in ``item_id``, which the schema keeps null for anything run
    # scoped. Resolving it here is what lets a reader address that review by
    # the item it is about instead of only by the run it ran in.
    item_id = (
        value.get("item_id")
        or value.get("epic_id")
        or value.get("deployment_member_item_id")
    )
    if item_id is not None:
        # The item is looked up whether or not a plan already named the
        # project: the reviewer is told which item they are judging, and a
        # plan-homed requirement is still attached to one.
        item = conn.execute(
            "SELECT i.project_id, i.title, i.project_sequence, "
            "pr.slug, pr.public_item_prefix "
            "FROM items i JOIN projects pr ON pr.id = i.project_id "
            f"WHERE i.id = {p}",
            (int(item_id),),
        ).fetchone()
        if item is not None:
            if value.get("project_id") is None:
                value["project_id"] = int(item[0])
            value["item_title"] = str(item[1])
            value["item_ref"] = format_item_ref(
                str(item[3]), str(item[4] or ""), int(item[2])
            )
    if value.get("project_id") is None and value.get("deployment_run_id"):
        project = conn.execute(
            f"SELECT project_id FROM deployment_runs WHERE id = {p}",
            (str(value["deployment_run_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
    if value.get("project_id") is None:
        raise ValueError(f"QA requirement {requirement_id} has no project authority")
    return value


def review_subject(requirement: dict[str, Any]) -> dict[str, Any]:
    """Name what this review is a review OF, from the requirement's own home.

    An item's verification review and a deployment run's post-release review
    are different decisions with the same shape, and a surface that cannot
    tell them apart offers to block a release that already shipped.
    """
    if requirement.get("deployment_run_id"):
        kind = "deployment_run"
    elif requirement.get("item_id") or requirement.get("epic_id"):
        kind = "item"
    else:
        kind = "plan"
    return {
        "kind": kind,
        "item_id": (
            int(requirement["item_id"])
            if requirement.get("item_id") is not None
            else None
        ),
        #: The item a run-scoped check was recorded for. A reader that must
        #: address this review by item cannot recover it from ``item_id``,
        #: which the schema keeps null for anything run scoped.
        "deployment_member_item_id": (
            int(requirement["deployment_member_item_id"])
            if requirement.get("deployment_member_item_id") is not None
            else None
        ),
        "item_ref": requirement.get("item_ref"),
        "item_title": requirement.get("item_title"),
        "deployment_run_id": requirement.get("deployment_run_id"),
        "target_environment": requirement.get("target_env"),
        "qa_phase": str(requirement.get("qa_phase") or ""),
    }


def is_agent_verdict(conn: Any, requirement_id: int, performed_by: Any) -> bool:
    """Return whether this run's verdict is one a person is owed a review of.

    The discriminator is the requirement's own ``verdict_path``, not the
    string in ``performed_by``. A Browser or Terminal inspection is judged by
    an agent and refuses ``performed_by='agent'`` outright — its runs are
    recorded under the substrate that captured them — so keying on that
    string meant an undetermined inspection verdict raised no review request
    and reached nobody, while the method's own contract promised the item
    would halt for owner or operator review.
    """
    if str(performed_by or "") == "agent":
        return True
    p = _p(conn)
    row = conn.execute(
        f"SELECT verdict_path FROM qa_requirements WHERE id = {p}",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return False
    verdict_path = row["verdict_path"] if hasattr(row, "keys") else row[0]
    return str(verdict_path or "") == "agent"


__all__ = [
    "frozen_target_facts",
    "is_agent_verdict",
    "requirement_facts",
    "review_subject",
]
