"""Path-claim preparation and lifecycle checks for selected Dash posture."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain.check_path_claim_coverage_at_commit import (
    files_outside_coverage,
)
from yoke_core.domain.dash_posture_read import (
    failure,
    item_row,
    marker,
    posture,
)
from yoke_core.domain.schema_common import _table_exists


_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")


def _claim_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    if not all(
        _table_exists(conn, table)
        for table in (
            "path_claims",
            "path_claim_targets",
            "path_targets",
        )
    ):
        return []
    placeholder = marker(conn)
    state_markers = ", ".join(placeholder for _ in _NON_TERMINAL_CLAIM_STATES)
    cursor = conn.execute(
        "SELECT pc.id, pc.state, pt.path_string "
        "FROM path_claims pc "
        "LEFT JOIN path_claim_targets pct ON pct.claim_id = pc.id "
        "LEFT JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pc.owner_kind = 'item' AND pc.owner_item_id = {placeholder} "
        f"AND pc.state IN ({state_markers}) "
        "ORDER BY pc.id, pt.path_string",
        (int(item_id), *_NON_TERMINAL_CLAIM_STATES),
    )
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _claim_coverage(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[int], list[str], list[str]]:
    claim_ids: list[int] = []
    states: list[str] = []
    paths: list[str] = []
    for row in rows:
        claim_id = int(row["id"])
        if claim_id not in claim_ids:
            claim_ids.append(claim_id)
            states.append(str(row["state"]))
        path = str(row.get("path_string") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return claim_ids, states, paths


def ensure_survey_path_claim(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    touch_paths: Iterable[str],
    integration_target: str,
) -> Optional[int]:
    """Register or widen the selected Dash claim from its live survey."""
    item = item_row(conn, item_id)
    selected = posture(item)
    if str(item["workflow_id"]) != "dash" or selected.get("path_claims") is not True:
        return None
    paths = list(
        dict.fromkeys(str(path).strip() for path in touch_paths if str(path).strip())
    )
    if not paths:
        raise ValueError("Dash path-claims posture requires at least one surveyed path")
    rows = _claim_rows(conn, item_id)
    claim_ids, states, declared = _claim_coverage(rows)
    missing = files_outside_coverage(paths, declared)
    actor_value = item.get("actor_id")
    actor_id = (
        int(actor_value)
        if actor_value is not None and str(actor_value).isdigit()
        else None
    )
    if not claim_ids:
        from yoke_core.domain.path_claims_register import register_for_item

        return register_for_item(
            conn,
            item_id=int(item_id),
            integration_target=str(integration_target),
            paths=paths,
            actor_id=actor_id,
            session_id=session_id,
            allow_planned=True,
        )
    if not missing:
        return claim_ids[0]
    candidate = next(
        (
            claim_id
            for claim_id, state in zip(claim_ids, states)
            if state in {"active", "planned"}
        ),
        None,
    )
    if candidate is None:
        raise ValueError("Dash path claim is blocked and cannot absorb surveyed paths")
    from yoke_core.domain.path_claims_amend import widen
    from yoke_core.domain.path_claims_resolve import (
        resolve_or_plan_paths_to_target_ids,
    )

    target_ids = resolve_or_plan_paths_to_target_ids(
        conn,
        int(item["project_id"]),
        missing,
        item_id=int(item_id),
        claim_id=int(candidate),
        session_id=session_id,
    )
    widen(
        conn,
        claim_id=int(candidate),
        add_target_ids=target_ids,
        reason="Align the Dash path claim with its live conflict survey.",
    )
    return int(candidate)


def activation_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    claim_ids, states, paths = _claim_coverage(_claim_rows(conn, item_id))
    if not claim_ids or not paths:
        return failure(
            "GATE_DASH_PATH_CLAIM_REQUIRED",
            "Selected Dash path-claims posture has no concrete claim coverage.",
            "Record a non-empty conflict survey and prepare the Dash worktree.",
        )
    if any(state != "active" for state in states):
        return failure(
            "GATE_DASH_PATH_CLAIM_INACTIVE",
            "Every non-terminal Dash path claim must be active before execution.",
            "Resolve upstream coordination and rerun worktree preparation.",
        )
    return None


def completion_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    active = activation_gate(conn, item_id)
    if active is not None:
        return active
    from yoke_core.domain.dash_execution import (
        DASH_EVIDENCE_SECTION,
        read_json_section,
    )

    evidence = read_json_section(
        conn,
        item_id=item_id,
        section=DASH_EVIDENCE_SECTION,
    )
    if evidence is None:
        return failure(
            "GATE_DASH_PATH_EVIDENCE_REQUIRED",
            "Dash path coverage needs the persisted merged-file evidence.",
            "Record Dash execution evidence with the exact touched paths.",
        )
    if evidence.get("no_changes"):
        return None
    _, _, declared = _claim_coverage(_claim_rows(conn, item_id))
    missing = files_outside_coverage(
        evidence.get("touched_files") or (),
        declared,
    )
    if missing:
        return failure(
            "GATE_DASH_PATH_CLAIM_COVERAGE",
            "Merged Dash paths fall outside the active claim: " + ", ".join(missing),
            "Widen the claim through the sanctioned coordination surface.",
        )
    return None


__all__ = ["activation_gate", "completion_gate", "ensure_survey_path_claim"]
