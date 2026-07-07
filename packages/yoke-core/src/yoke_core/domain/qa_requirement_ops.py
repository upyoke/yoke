"""QA requirement read and mutation ops (list/get/waive/update).

Sibling module to ``qa_requirements`` owned by the QA domain. Hosts the
read-side and post-creation mutation surfaces so the parent shim keeps only
the requirement-add CRUD path. Lifecycle events flow through the shared
``qa_events.emit_qa_requirement_event`` helper instead of a duplicated
local copy.

This module imports its constants and tiny helpers exclusively from
``yoke_core.domain.qa_constants`` to keep the dependency direction
``qa_constants ← qa_requirement_ops`` and avoid an import cycle with the
parent ``qa_requirements`` shim.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
)
from yoke_core.domain.qa_constants import (
    VALID_BLOCKING_MODES,
    VALID_BROWSER_QA_KINDS,
    VALID_QA_PHASES,
    _REQ_SELECT,
    _normalize_qa_phase,
    _pipe_row,
)
from yoke_core.domain.qa_events import emit_qa_requirement_event


# ---------------------------------------------------------------------------
# requirement-list
# ---------------------------------------------------------------------------

def cmd_requirement_list(
    *,
    db_path: Optional[str] = None,
    item_id: Optional[int] = None,
    epic_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
) -> List[str]:
    """List requirements (pipe-delimited). Returns list of formatted lines."""
    conn = connect(path=db_path)
    try:
        where = "1=1"
        params: list = []
        if item_id is not None:
            where = "item_id = %s"
            params.append(item_id)
        elif epic_id is not None:
            where = "epic_id = %s"
            params.append(epic_id)
        elif deployment_run_id is not None:
            where = "deployment_run_id = %s"
            params.append(deployment_run_id)

        rows = query_rows(conn, f"SELECT {_REQ_SELECT} FROM qa_requirements WHERE {where} ORDER BY id", tuple(params))
    finally:
        conn.close()

    lines = []
    for row in rows:
        line = _pipe_row(row)
        print(line)
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# requirement-get
# ---------------------------------------------------------------------------

def cmd_requirement_get(
    req_id: int,
    *,
    db_path: Optional[str] = None,
) -> str:
    """Get a single requirement (pipe-delimited). Returns the formatted line."""
    if req_id is None:
        print("Usage: qa requirement-get <id>", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        row = query_one(conn, f"SELECT {_REQ_SELECT} FROM qa_requirements WHERE id = %s", (req_id,))
    finally:
        conn.close()

    if row is None:
        print(f"Error: requirement {req_id} not found", file=sys.stderr)
        sys.exit(1)

    line = _pipe_row(row)
    print(line)
    return line


# ---------------------------------------------------------------------------
# requirement-waive
# ---------------------------------------------------------------------------

def waive_requirement(
    conn,
    req_id: int,
    rationale: str,
    *,
    db_path: Optional[str] = None,
    source: str = "agent",
    force: bool = False,
) -> None:
    """Waive one requirement using a caller-owned connection."""
    row = query_one(
        conn,
        """SELECT blocking_mode, qa_kind, qa_phase, item_id, epic_id, task_num, deployment_run_id
           FROM qa_requirements WHERE id = %s""",
        (req_id,),
    )
    if row is None:
        raise LookupError(f"requirement {req_id} not found")

    blocking_mode = row["blocking_mode"]
    qa_kind = row["qa_kind"]

    if blocking_mode == "blocking" and not force:
        raise PermissionError(
            f"requirement {req_id} is blocking (qa_kind={qa_kind}). "
            "Waiving a blocking requirement requires force=True."
        )

    now = iso8601_now()
    conn.execute(
        """UPDATE qa_requirements
           SET waived_at = %s, waiver_rationale = %s, waiver_source = %s
           WHERE id = %s""",
        (now, rationale, source, req_id),
    )
    conn.commit()

    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementWaived",
        requirement_id=req_id,
        qa_kind=qa_kind,
        qa_phase=str(row["qa_phase"]),
        rationale=rationale,
        source=source,
        target_row=row,
    )


def cmd_requirement_waive(
    req_id: int,
    rationale: str,
    *,
    db_path: Optional[str] = None,
    source: str = "agent",
    force: bool = False,
) -> None:
    """Waive a requirement. Validates blocking mode and records rationale."""
    if req_id is None or not rationale:
        print("Usage: qa requirement-waive <id> <rationale> [--source operator|agent] [--force]", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        try:
            waive_requirement(
                conn,
                req_id,
                rationale,
                db_path=db_path,
                source=source,
                force=force,
            )
        except LookupError:
            print(f"Error: requirement {req_id} not found", file=sys.stderr)
            sys.exit(1)
        except PermissionError:
            row = query_one(
                conn,
                "SELECT blocking_mode, qa_kind FROM qa_requirements WHERE id = %s",
                (req_id,),
            )
            qa_kind = row["qa_kind"] if row is not None else "unknown"
            print(
                f"Error: requirement {req_id} is blocking (qa_kind={qa_kind}). "
                "Waiving a blocking requirement requires --force.",
                file=sys.stderr,
            )
            print(
                f'Hint: If this is an operator decision, use: qa requirement-waive {req_id} "<rationale>" --source operator --force',
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        conn.close()

    print(f"Waived requirement {req_id} (source={source})")


# ---------------------------------------------------------------------------
# requirement-update
# ---------------------------------------------------------------------------

# Fields the caller may mutate through ``requirement-update``. Lifecycle /
# identity fields (``id``, ``qa_kind``, attachment keys, ``waived_at`` and
# friends, ``created_at``) are deliberately excluded — mutating those would
# change what the requirement *is*, not how it validates. Use ``requirement-add``
# + ``requirement-waive`` instead.
UPDATABLE_REQUIREMENT_FIELDS: tuple[str, ...] = (
    "success_policy",
    "blocking_mode",
    "target_env",
    "capability_requirements",
    "suite_id",
    "qa_phase",
)


def cmd_requirement_update(
    req_id: int,
    field: str,
    value: Optional[str],
    *,
    db_path: Optional[str] = None,
) -> None:
    """Update a mutable field on an existing QA requirement.

    Field allowlist: ``success_policy``, ``blocking_mode``, ``target_env``,
    ``capability_requirements``, ``suite_id``, ``qa_phase``. Other fields are
    rejected; ``qa_kind`` in particular must not be mutated here — use
    ``requirement-waive`` plus a fresh ``requirement-add`` when the verification
    surface needs to change.

    Validates enum fields (``blocking_mode``, ``qa_phase``) against the
    canonical constants. Validates ``success_policy`` as JSON when the existing
    row is a browser QA kind.

    Emits a ``QARequirementUpdated`` lifecycle event carrying the field name
    and the new value. The prior value is not logged to keep event size small
    and to avoid leaking potentially large policy bodies.
    """
    if req_id is None:
        print("Usage: qa requirement-update <id> <field> [value]", file=sys.stderr)
        sys.exit(2)
    if not field:
        print("Usage: qa requirement-update <id> <field> [value]", file=sys.stderr)
        sys.exit(2)

    if field == "qa_kind":
        print(
            "Error: qa_kind is not updatable. Use requirement-waive + requirement-add "
            "to replace the verification surface.",
            file=sys.stderr,
        )
        sys.exit(2)
    if field not in UPDATABLE_REQUIREMENT_FIELDS:
        print(
            f"Error: field '{field}' is not updatable. Allowed: "
            f"{', '.join(UPDATABLE_REQUIREMENT_FIELDS)}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Enum validation mirrors the add path.
    if field == "blocking_mode":
        if value not in VALID_BLOCKING_MODES:
            print(
                f"Error: blocking_mode must be one of {sorted(VALID_BLOCKING_MODES)}",
                file=sys.stderr,
            )
            sys.exit(2)
    if field == "qa_phase":
        normalized = _normalize_qa_phase(value or "")
        if normalized not in VALID_QA_PHASES:
            print(
                f"Error: qa_phase must be one of {sorted(VALID_QA_PHASES)}",
                file=sys.stderr,
            )
            sys.exit(2)
        value = normalized

    conn = connect(path=db_path)
    try:
        existing = query_one(
            conn,
            "SELECT qa_kind, qa_phase, item_id, epic_id, task_num, deployment_run_id "
            "FROM qa_requirements WHERE id = %s",
            (req_id,),
        )
        if existing is None:
            print(f"Error: requirement {req_id} not found", file=sys.stderr)
            sys.exit(1)

        # Browser QA policy fields must be JSON to survive round-tripping
        # through the executor.
        if field == "success_policy" and existing["qa_kind"] in VALID_BROWSER_QA_KINDS:
            if value is not None and value != "":
                try:
                    json.loads(value)
                except json.JSONDecodeError as exc:
                    print(
                        f"Error: success_policy must be valid JSON for qa_kind="
                        f"{existing['qa_kind']}: {exc}",
                        file=sys.stderr,
                    )
                    sys.exit(2)

        conn.execute(
            f"UPDATE qa_requirements SET {field} = %s WHERE id = %s",
            (value, req_id),
        )
        conn.commit()

        # Resolve phase for event payload (use updated value when qa_phase
        # was the mutated field; otherwise fall back to the existing row).
        event_phase = value if field == "qa_phase" else str(existing["qa_phase"])
        emit_qa_requirement_event(
            conn,
            db_path=db_path,
            event_name="QARequirementUpdated",
            requirement_id=req_id,
            qa_kind=str(existing["qa_kind"]),
            qa_phase=event_phase,
            extra_detail={"field": field, "new_value": value},
            target_row=existing,
        )
    finally:
        conn.close()

    print(f"Updated requirement {req_id}: {field}")
