"""Read current acceptance identities without changing their validation rules."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import qa_execution_environment_target as target_authority
from yoke_core.domain.deployment_qa_presentation_facts import (
    requirement_row,
    subject_requirement_rows,
    presented_run_ids,
)
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read
from yoke_core.domain.db_helpers import query_rows


def presented_item_answer_rows(conn, item_id):
    from yoke_core.domain.deployment_qa_presentation_facts import (
        presented_member_ids,
        attachment_rows,
    )

    members = presented_member_ids(conn)
    if members is None or item_id not in members:
        return None

    def read():
        from yoke_core.domain.qa_obligation_settlement import (
            requirement_retracted_at_select,
        )

        markers = ",".join("%s" for _ in members)
        rows = query_rows(
            conn,
            "SELECT item_id,qa_phase,qa_kind,waived_at,waiver_rationale,instructions,"
            f"{requirement_retracted_at_select(conn)} FROM qa_requirements "
            f"WHERE item_id IN ({markers}) AND deployment_run_id IS NULL "
            "AND qa_phase='post_deploy' AND plan_id IS NULL",
            members,
        )
        by_item = {}
        for row in rows:
            by_item.setdefault(int(row["item_id"]), []).append(row)
        return by_item

    rows = presentation_read(conn, ("qa_item_intake_answers", members), read)
    attached = [
        {"qa_phase": "post_deploy", "retracted_at": not row["live"]}
        for row in attachment_rows(conn, item_id)
    ]
    return attached, rows.get(item_id, [])


def presented_pending_review(conn, run_id, stage, member, digest):
    runs = presented_run_ids(conn, run_id)
    if not runs:
        return None, False

    def read():
        from yoke_core.domain.qa_pending_agent_review import _PENDING_REVIEW_SQL

        markers = ",".join("%s" for _ in runs)
        return query_rows(
            conn,
            f"{_PENDING_REVIEW_SQL} AND e.deployment_run_id IN ({markers}) "
            "ORDER BY e.created_at DESC,e.id DESC",
            runs,
        )

    rows = presentation_read(conn, ("qa_pending_reviews", runs), read)
    row = next(
        (
            value
            for value in rows
            if value["deployment_run_id"] == run_id
            and value["deployment_stage"] == stage
            and (value["deployment_member_item_id"] or 0) == (member or 0)
            and value["execution_target_digest"] == digest
        ),
        None,
    )
    return row, True


def presented_artifact_counts(conn, requested):
    runs = presented_run_ids(conn)
    if not runs:
        return None

    def read():
        markers = ",".join("%s" for _ in runs)
        rows = query_rows(
            conn,
            "SELECT r.id AS qa_run_id,a.artifact_type,COUNT(a.id) AS artifact_count "
            "FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            "LEFT JOIN qa_artifacts a ON a.qa_run_id=r.id "
            f"WHERE q.deployment_run_id IN ({markers}) "
            "GROUP BY r.id,a.artifact_type",
            runs,
        )
        counts = {}
        for row in rows:
            types = counts.setdefault(int(row["qa_run_id"]), {})
            if row["artifact_count"]:
                types[str(row["artifact_type"])] = int(row["artifact_count"])
        return counts

    counts = presentation_read(conn, ("qa_presented_artifact_counts", runs), read)
    if not set(requested) <= counts.keys():
        return None
    return {run: counts[run] for run in requested if counts[run]}


def acceptance_waived(conn: Any, requirement_id: int) -> bool:
    """True when an authorized waiver already discharged this requirement."""
    row = requirement_row(conn, requirement_id)
    if row is not None:
        return bool(row["waived_at"])
    row = conn.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (int(requirement_id),)
    ).fetchone()
    if row is None:
        return False
    return bool(row["waived_at"] if hasattr(row, "keys") else row[0])


def completed_execution(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[str, Any] | None:
    """The newest completed execution recorded against this exact target.

    The digest predicate is the target-identity check: an execution
    recorded against a replaced target simply is not selected, so a
    superseded producer receipt can never answer for the current one.
    """
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    runs = presented_run_ids(conn, run_id)
    if runs:

        def read():
            markers = ",".join("%s" for _ in runs)
            return query_rows(
                conn,
                "SELECT * FROM qa_plan_executions "
                f"WHERE deployment_run_id IN ({markers}) AND state='completed' "
                "ORDER BY created_at DESC,id DESC",
                runs,
            )

        rows = presentation_read(conn, ("qa_completed_executions", runs), read)
        row = next(
            (
                value
                for value in rows
                if value["deployment_run_id"] == run_id
                and value["deployment_stage"] == stage_name
                and (value["deployment_member_item_id"] or 0) == (member_item_id or 0)
                and value["execution_target_digest"] == execution_target_digest
            ),
            None,
        )
        if row is None:
            return None
        from yoke_core.domain.qa_plan_execution_target_snapshot import (
            materialized_execution,
        )

        return presentation_read(
            conn,
            ("qa_completed_execution", str(row["id"])),
            lambda: materialized_execution(row),
        )
    else:
        row = conn.execute(
            "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
            "AND deployment_stage=%s "
            "AND COALESCE(deployment_member_item_id,0)=%s "
            "AND execution_target_digest=%s AND state='completed' "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (run_id, stage_name, member_item_id or 0, execution_target_digest),
        ).fetchone()
    if row is None:
        return None
    execution_id = row["id"] if hasattr(row, "keys") else row[0]
    return select_plan_execution(conn, str(execution_id), lock=False)


def stopped_case_execution(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[str, Any] | None:
    """The newest aborted or errored execution on this exact target.

    Callers read it only once every case already passed on the target: the
    passes may come from several stopped walks, and replaying the roster to
    obtain a completed one would prove nothing new.
    """
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    row = conn.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND execution_target_digest=%s AND state IN ('aborted','error') "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (run_id, stage_name, member_item_id or 0, execution_target_digest),
    ).fetchone()
    if row is None:
        return None
    execution_id = row["id"] if hasattr(row, "keys") else row[0]
    return select_plan_execution(conn, str(execution_id), lock=False)


def existing_acceptance_requirement(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    acceptance_qa_kind: str,
) -> int | None:
    """This subject's acceptance requirement for the target, if it exists.

    ``None`` means no acceptance requirement has been materialized for
    this exact target yet. A stage whose target was replaced keeps its
    older requirement rows untouched and unmatched -- the replacement
    target gets its own row rather than inheriting the earlier verdict.
    """
    run_id = str(subject["id"])
    stage_name = str(subject["stage"]["name"])
    member = subject.get("member_item_id")
    rows = subject_requirement_rows(conn, run_id, stage_name, member)
    if rows is not None:
        rows = [row for row in rows if row["qa_kind"] == acceptance_qa_kind]
    else:
        rows = conn.execute(
            "SELECT id,execution_target_json,execution_target_digest "
            "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND COALESCE(deployment_member_item_id,0)=%s AND qa_kind=%s "
            "ORDER BY id",
            (run_id, stage_name, member or 0, acceptance_qa_kind),
        ).fetchall()
    expected_json = target_authority.canonical_target(target)
    expected_digest = target_authority.target_digest(target)
    matches = [
        row
        for row in rows
        if str(row["execution_target_json"] or "") == expected_json
        and str(row["execution_target_digest"] or "") == expected_digest
    ]
    if len(matches) > 1:
        raise ValueError(
            "deployment stage acceptance was materialized more than once; "
            "resolve the duplicate before resuming the pipeline"
        )
    if not matches:
        return None
    row = matches[0]
    return int(row["id"] if hasattr(row, "keys") else row[0])
