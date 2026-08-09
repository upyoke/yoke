"""Make the current built-in definitions available without policing history.

A universe's ``workflow_versions`` rows are its data. Convergence ensures the
current code-owned definition exists there as a version, and does nothing else
to what is already stored: it never rewrites a row, never renumbers one, never
deletes one, and never refuses to boot because a stored definition differs from
what the code expected at that number.

That refusal is what this replaced, and it was a fleet-wide outage twice. Boot
convergence ran for every tenant and compared each stored row against a
code-owned fixture *by version number*, so a universe that had published on its
own schedule -- which is what a staging environment is for -- was
indistinguishable from a corrupted one, and one mismatched row crash-looped
everything.

Recognition replaced enforcement. Whether a stored definition is one Yoke
published is answered by digest against the canon, at whatever number the
universe stores it under, and reported through
:func:`unrecognized_builtin_versions` as a health finding scoped to that one
universe. See ``builtin_workflow_canon``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_canon import recognize
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definitions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry_rows import (
    version_by_id,
    workflow_row,
)
from yoke_core.domain.workflow_registry_sql import marker, row_dict, rows_dict

InsertVersion = Callable[..., dict]


def _locked_workflow_row(conn: Any, workflow_id: str) -> Optional[dict]:
    """Read one workflow, locking it first on PostgreSQL."""
    if not db_backend.connection_is_postgres(conn):
        return workflow_row(conn, workflow_id)
    bind = marker(conn)
    cursor = conn.execute(
        f"SELECT * FROM workflows WHERE id = {bind} FOR UPDATE",
        (workflow_id,),
    )
    return row_dict(cursor, cursor.fetchone())


def _matching_version(
    conn: Any,
    workflow_id: str,
    definition: Mapping[str, Any],
) -> Optional[dict]:
    """The universe's own row holding *definition*, if it has one.

    Matched by digest alone, the same way :func:`recognize` matches canon.
    Comparing the stored JSON byte-for-byte would make an equivalent row that
    happens to be serialized differently look like a new definition, and
    convergence would append a duplicate of what the universe already had.
    That serialization sensitivity is what produced the first outage, when a
    governed migration rewrote these rows through a different serializer.
    """
    bind = marker(conn)
    cursor = conn.execute(
        "SELECT * FROM workflow_versions "
        f"WHERE workflow_id = {bind} AND definition_digest = {bind} "
        "ORDER BY version LIMIT 1",
        (workflow_id, definition_digest(definition)),
    )
    for row in rows_dict(cursor):
        return row
    return None


def _ensure_current_version(
    conn: Any,
    fixture: Mapping[str, Any],
    insert_version: InsertVersion,
) -> dict:
    """Make the current definition available, appending it if absent.

    Appends at the universe's own ``MAX(version) + 1``. Version numbers are
    that universe's sequence positions, so two universes adopting the same
    definition on different schedules number it differently and neither is
    wrong.
    """
    workflow_id = str(fixture["workflow"]["id"])
    definition = fixture["definition"]
    validate_workflow_definition(definition)
    existing = _matching_version(conn, workflow_id, definition)
    if existing is not None:
        return existing
    bind = marker(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM workflow_versions "
        f"WHERE workflow_id = {bind}",
        (workflow_id,),
    ).fetchone()
    return insert_version(
        conn,
        workflow_id=workflow_id,
        version=int(row[0]) + 1,
        definition=definition,
        published_by_actor_id=None,
    )


def _adopts_automatically(
    workflow: Mapping[str, Any],
    selected: Mapping[str, Any],
    desired: Mapping[str, Any],
) -> bool:
    """Whether this boot may move the workflow onto the code-owned version.

    Three things must hold. There has to be somewhere to move to, so a universe
    already on the desired version is left untouched rather than rewritten. The
    workflow must be following, which a local publication turns off. And the
    version being left has to be one the canon recognizes -- an edited
    definition is customization, and taking a new generation over the top of it
    would discard an operator's work without asking.
    """
    if int(selected["id"]) == int(desired["id"]):
        return False
    if str(workflow.get("canon_follow") or "auto") != "auto":
        return False
    return recognize(
        str(workflow["id"]), str(selected["definition_digest"])
    ) is not None


def unrecognized_builtin_versions(conn: Any) -> list[dict]:
    """Stored built-in rows whose content the canon does not recognize.

    Read-only, and deliberately not consulted by boot. A universe carrying a
    definition Yoke never published is worth surfacing -- it is either a local
    customization or real corruption -- but it is a fact about that one
    universe, so it belongs in its health report rather than in a startup
    abort that takes the fleet with it.
    """
    findings: list[dict] = []
    bind = marker(conn)
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        cursor = conn.execute(
            "SELECT workflow_id, version, definition_digest FROM workflow_versions "
            f"WHERE workflow_id = {bind} ORDER BY version",
            (workflow_id,),
        )
        for row in rows_dict(cursor):
            digest = str(row["definition_digest"])
            if recognize(workflow_id, digest) is None:
                findings.append(
                    {
                        "workflow_id": workflow_id,
                        "version": int(row["version"]),
                        "definition_digest": digest,
                    }
                )
    return findings


def converge_builtin_workflows(
    conn: Any,
    *,
    insert_version: InsertVersion,
) -> None:
    """Register the built-in workflows and make current definitions available."""
    now = iso8601_now()
    bind = marker(conn)
    for current_fixture in builtin_workflow_definitions():
        workflow = current_fixture["workflow"]
        workflow_id = str(workflow["id"])
        existing_workflow = _locked_workflow_row(conn, workflow_id)
        if existing_workflow is None:
            conn.execute(
                "INSERT INTO workflows "
                "(id, name, description, source, status, current_version_id, "
                "created_at, updated_at) "
                f"VALUES ({bind}, {bind}, {bind}, {bind}, "
                f"'active', NULL, {bind}, {bind})",
                (
                    workflow_id,
                    workflow["name"],
                    workflow["description"],
                    workflow["source"],
                    now,
                    now,
                ),
            )
        elif existing_workflow["source"] != "built_in":
            raise WorkflowRegistryError(
                f"built-in workflow id {workflow_id!r} is owned by "
                f"{existing_workflow['source']!r}"
            )
        else:
            conn.execute(
                f"UPDATE workflows SET name = {bind}, "
                f"description = {bind}, updated_at = {bind} "
                f"WHERE id = {bind}",
                (
                    workflow["name"],
                    workflow["description"],
                    now,
                    workflow_id,
                ),
            )

        desired = _ensure_current_version(conn, current_fixture, insert_version)
        current = workflow_row(conn, workflow_id)
        if current is None:
            raise WorkflowRegistryError(f"workflow {workflow_id!r} is missing")
        current_id = current.get("current_version_id")
        selected = (
            version_by_id(conn, int(current_id))
            if current_id is not None
            else None
        )
        if selected is not None and selected["workflow_id"] != workflow_id:
            raise WorkflowRegistryError(
                f"workflow {workflow_id!r} has an invalid current version"
            )
        if selected is None:
            # Unset and dangling are the same question here: a pointer at a row
            # that is not there carries no information, so both re-resolve to
            # the code-owned version below. Retiring a redundant version can
            # leave this column naming the row it dropped, and this convergence
            # runs before the migration history does — so the boot that retires
            # it succeeds and every later boot would refuse, with no migration
            # able to repair it, because the refusal happens first. A pointer
            # into a DIFFERENT workflow stays fatal: that is a real mix-up
            # rather than a missing row.
            conn.execute(
                f"UPDATE workflows SET current_version_id = {bind}, "
                f"updated_at = {bind} WHERE id = {bind}",
                (int(desired["id"]), now, workflow_id),
            )
        elif _adopts_automatically(current, selected, desired):
            # A universe running an unmodified published generation has nothing
            # to decide about the next one, so it takes it and is told after the
            # fact. A universe that edited its definition is left alone: there an
            # update is a merge, and no automatic resolution is correct.
            conn.execute(
                f"UPDATE workflows SET current_version_id = {bind}, "
                f"canon_adopted_from_version = {bind}, updated_at = {bind} "
                f"WHERE id = {bind}",
                (
                    int(desired["id"]),
                    int(selected["version"]),
                    now,
                    workflow_id,
                ),
            )
    conn.commit()


def select_current_builtin_workflow_versions(
    conn: Any,
    *,
    insert_version: InsertVersion,
) -> dict[str, int]:
    """Select code-owned revisions without changing existing item pins."""
    selected: dict[str, int] = {}
    bind = marker(conn)
    for fixture in builtin_workflow_definitions():
        workflow_id = str(fixture["workflow"]["id"])
        workflow = _locked_workflow_row(conn, workflow_id)
        if workflow is None:
            raise WorkflowRegistryError(f"workflow {workflow_id!r} is missing")
        if workflow["source"] != "built_in":
            raise WorkflowRegistryError(
                f"built-in workflow id {workflow_id!r} is owned by "
                f"{workflow['source']!r}"
            )
        target = _ensure_current_version(conn, fixture, insert_version)
        conn.execute(
            f"UPDATE workflows SET current_version_id = {bind}, "
            f"updated_at = {bind} WHERE id = {bind}",
            (int(target["id"]), iso8601_now(), workflow_id),
        )
        selected[workflow_id] = int(target["version"])
    return selected


__all__ = [
    "converge_builtin_workflows",
    "select_current_builtin_workflow_versions",
    "unrecognized_builtin_versions",
]
