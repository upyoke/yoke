"""Set reads for the members of one read-only QA presentation."""

from collections import defaultdict
from contextvars import ContextVar
from functools import wraps
import json
from collections.abc import Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

_MEMBERS = ContextVar("qa_presentation_members", default=None)


def member_presentation(function):
    @wraps(function)
    def run(conn, subjects):
        token = _MEMBERS.set(
            (
                conn,
                tuple(sorted({item for _, item, _ in subjects})),
                tuple(sorted({run for run, _, _ in subjects})),
            )
        )
        try:
            return function(conn, subjects)
        finally:
            _MEMBERS.reset(token)

    return run


def attachment_rows(conn, member):
    """All attachment facts in one read; None keeps scalar callers unchanged."""
    scope = _MEMBERS.get()
    if scope is None or scope[0] is not conn or member not in scope[1]:
        return None
    members = scope[1]

    def read():
        from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql

        markers = ",".join("%s" for _ in members)
        rows = query_rows(
            conn,
            "SELECT a.item_id,a.plan_id,p.id AS live_plan_id,p.target_environment_id,"
            f"p.retired_at,{live_item_attachment_sql(conn, 'a')} AS live "
            "FROM qa_plan_item_attachments a LEFT JOIN qa_plans p ON p.id=a.plan_id "
            f"WHERE a.item_id IN ({markers}) AND a.qa_phase='post_deploy' "
            "ORDER BY a.plan_id",
            members,
        )
        by_member = defaultdict(list)
        for row in rows:
            by_member[int(row["item_id"])].append(row)
        return by_member

    return presentation_read(conn, ("qa_member_attachments", members), read).get(
        member, []
    )


def run_member_rows(conn, run_id):
    scope = _MEMBERS.get()
    if scope is None or scope[0] is not conn or run_id not in scope[2]:
        return None

    def read():
        markers = ",".join("%s" for _ in scope[2])
        rows = query_rows(
            conn,
            "SELECT dri.run_id,dri.item_id,dri.requirement_snapshot,i.project_id "
            "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
            f"WHERE dri.run_id IN ({markers})",
            scope[2],
        )
        by_run = defaultdict(dict)
        for row in rows:
            by_run[str(row["run_id"])][int(row["item_id"])] = row
        return by_run

    return presentation_read(conn, ("qa_presented_members", scope[2]), read).get(
        run_id, {}
    )


def withdrawn_requirement_ids(conn, requested):
    """Read withdrawals of exactly the frozen source IDs, without an item join."""
    scope = _MEMBERS.get()
    if scope is None or scope[0] is not conn or not scope[2]:
        return None

    def read():
        from yoke_core.domain.qa_obligation_settlement import (
            unretracted_requirement_sql,
        )

        ids = set()
        for run in scope[2]:
            for row in run_member_rows(conn, run).values():
                raw = row["requirement_snapshot"]
                try:
                    snapshot = raw if isinstance(raw, Mapping) else json.loads(str(raw))
                except (ValueError, TypeError):
                    continue  # The canonical subject reader reports malformed snapshots.
                if not isinstance(snapshot, Mapping):
                    continue
                for requirement in snapshot.get("requirements") or []:
                    if (
                        isinstance(requirement, Mapping)
                        and requirement.get("id") is not None
                    ):
                        try:
                            ids.add(int(requirement["id"]))
                        except (TypeError, ValueError):
                            continue
        if not ids:
            return ids, set()
        markers = ",".join("%s" for _ in ids)
        rows = query_rows(
            conn,
            f"SELECT id FROM qa_requirements WHERE id IN ({markers}) "
            f"AND NOT ({unretracted_requirement_sql(conn)})",
            tuple(sorted(ids)),
        )
        return ids, {int(row["id"]) for row in rows}

    known, withdrawn = presentation_read(
        conn, ("qa_source_withdrawals", scope[2]), read
    )
    return withdrawn.intersection(requested) if set(requested) <= known else None


def presented_run_ids(conn, run_id=None):
    scope = _MEMBERS.get()
    if (
        scope is None
        or scope[0] is not conn
        or (run_id is not None and run_id not in scope[2])
    ):
        return None
    return scope[2]


def presented_member_ids(conn):
    scope = _MEMBERS.get()
    return scope[1] if scope is not None and scope[0] is conn else None


def presented_plan_ids(conn):
    runs, members = presented_run_ids(conn), presented_member_ids(conn)
    if not runs:
        return None

    def read():
        ids = {
            int(row["plan_id"])
            for rows in _requirements_by_stage(conn, runs).values()
            for row in rows
            if row["plan_id"] is not None
        }
        for member in members:
            ids.update(int(row["plan_id"]) for row in attachment_rows(conn, member))
        return tuple(sorted(ids))

    return presentation_read(conn, ("qa_presented_plan_ids", runs, members), read)


def run_facts(conn, run_id):
    runs = presented_run_ids(conn, run_id)
    if not runs:
        return None

    def read():
        markers = ",".join("%s" for _ in runs)
        rows = query_rows(
            conn,
            "SELECT dr.id,dr.project_id,p.slug AS project_slug,p.name AS project_name,"
            "o.id AS tenant_id,o.slug AS tenant_slug,o.name AS tenant_name,"
            "dr.flow,dr.status,dr.current_stage,dr.release_lineage,"
            "dr.artifact_identity,dr.composition_frozen_at,dr.requirement_snapshot,"
            "dr.bound_sources,"
            "df.definition_schema_version,df.stages "
            "FROM deployment_runs dr JOIN deployment_flows df ON df.id=dr.flow "
            "JOIN projects p ON p.id=dr.project_id JOIN organizations o ON o.id=p.org_id "
            f"WHERE dr.id IN ({markers})",
            runs,
        )
        return {str(row["id"]): dict(row) for row in rows}

    return presentation_read(conn, ("qa_presented_runs", runs), read).get(run_id)


def execution_rows(conn, requested):
    """Capture actual attempts together; canonical ordering grades only requested IDs."""
    runs = presented_run_ids(conn)
    if not runs:
        return None

    def read():
        from yoke_core.domain.qa_latest_execution import actual_execution_sql

        markers = ",".join("%s" for _ in runs)
        rows = query_rows(
            conn,
            "SELECT q.id AS presented_requirement_id,run.* FROM qa_requirements q "
            "LEFT JOIN qa_runs run ON run.qa_requirement_id=q.id "
            f"AND {actual_execution_sql('run')} "
            f"WHERE q.deployment_run_id IN ({markers})",
            runs,
        )
        by_requirement = defaultdict(list)
        for row in rows:
            requirement_id = int(row["presented_requirement_id"])
            by_requirement.setdefault(requirement_id, [])
            if row["id"] is not None:
                value = dict(row)
                value.pop("presented_requirement_id")
                by_requirement[requirement_id].append(value)
        return by_requirement

    by_requirement = presentation_read(conn, ("qa_presented_executions", runs), read)
    if not set(requested) <= by_requirement.keys():
        return None
    return [row for requirement in requested for row in by_requirement[requirement]]


def _requirements_by_stage(conn, runs):
    def read():
        from yoke_core.domain.qa_obligation_settlement import (
            unretracted_requirement_sql,
            settled_obligation_sql,
            requirement_retracted_at_select,
        )

        markers = ",".join("%s" for _ in runs)
        rows = query_rows(
            conn,
            "SELECT id,deployment_run_id,deployment_stage,deployment_member_item_id,"
            "plan_id,method_id,qa_kind,execution_target_json,execution_target_digest,"
            "plan_case_key,case_position,baseline_position,host_baseline,"
            "blocking_mode,waived_at,superseded_by_requirement_id,"
            f"replacement_requirement_id,{requirement_retracted_at_select(conn)},"
            f"{unretracted_requirement_sql(conn)} AS unretracted,"
            f"{settled_obligation_sql(conn)} AS settled FROM qa_requirements "
            f"WHERE deployment_run_id IN ({markers}) "
            "ORDER BY CASE WHEN method_id IS NOT NULL THEN 0 ELSE 1 END,id",
            runs,
        )
        by_stage = defaultdict(list)
        for row in rows:
            by_stage[(row["deployment_run_id"], row["deployment_stage"])].append(row)
        return by_stage

    return presentation_read(conn, ("qa_presented_requirements", runs), read)


def stage_requirement_rows(conn, run_id, stage):
    runs = presented_run_ids(conn, run_id)
    if not runs:
        return None
    return _requirements_by_stage(conn, runs).get((run_id, stage), [])


def subject_requirement_rows(conn, run_id, stage, member):
    rows = stage_requirement_rows(conn, run_id, stage)
    if rows is None:
        return None
    return sorted(
        (
            dict(row)
            for row in rows
            if (row["deployment_member_item_id"] or 0) == (member or 0)
        ),
        key=lambda row: int(row["id"]),
    )


def requirement_row(conn, requirement_id):
    runs = presented_run_ids(conn)
    if not runs:
        return None

    def read():
        by_id = {}
        for rows in _requirements_by_stage(conn, runs).values():
            for row in rows:
                by_id[int(row["id"])] = row
        return by_id

    return presentation_read(conn, ("qa_requirement_lookup", runs), read).get(
        int(requirement_id)
    )


def producer_receipts(conn, run_id, stage):
    runs = presented_run_ids(conn, run_id)
    if not runs:
        return None

    def read():
        markers = ",".join("%s" for _ in runs)
        rows = query_rows(
            conn,
            f"SELECT * FROM deployment_stage_receipts WHERE run_id IN ({markers}) "
            "ORDER BY attempt_number DESC",
            runs,
        )
        by_stage = defaultdict(list)
        for row in rows:
            by_stage[(row["run_id"], row["stage_name"])].append(dict(row))
        return by_stage

    return presentation_read(conn, ("qa_presented_receipts", runs), read).get(
        (run_id, stage), []
    )
