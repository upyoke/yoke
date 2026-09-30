"""Restore manual source bindings and validate immutable run inputs."""

import json

from yoke_core.domain.qa_plan_execution_store import marker, QaPlanExecutionStateError

SOURCE_KEYS = (
    "standalone_source_revision",
    "standalone_source_ref",
    "standalone_checkout_path",
)


def restore_standalone_source(conn, context):
    row = conn.execute(
        f"SELECT roster_json FROM qa_plan_executions WHERE id={marker(conn)}",
        (context["standalone_execution_id"],),
    ).fetchone()
    if row is not None:
        for case in json.loads(row[0]):
            if int(case["requirement_id"]) == int(context["requirement_id"]):
                context.update({key: case[key] for key in SOURCE_KEYS if key in case})
                return


def require_same_source(roster, *, source_revision, source_ref, checkout_path):
    requested = dict(zip(SOURCE_KEYS, (source_revision, source_ref, checkout_path)))
    for case in roster:
        for key, value in requested.items():
            if value is not None and key in case and value != case[key]:
                raise QaPlanExecutionStateError(
                    f"standalone_source_changed: {key} differs from the live run; "
                    "resume with its original inputs or abort it before starting fresh"
                )


def require_same_mission_roster(prior, roster):
    ignored = {"requirement_id", "standalone_execution_id"}

    def snapshot(cases):
        return [
            {key: value for key, value in case.items() if key not in ignored}
            for case in cases
        ]

    if snapshot(prior["roster"]) != snapshot(roster):
        raise QaPlanExecutionStateError(
            "standalone_mission_roster_changed: continuation must retain the settled plan snapshot; "
            "restore the plan and source inputs before continuing the preserved host"
        )
