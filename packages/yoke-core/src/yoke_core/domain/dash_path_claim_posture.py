"""Path-claim preparation and lifecycle checks for selected Dash posture."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain.path_claim_coverage import (
    files_outside_coverage,
)
from yoke_core.domain.dash_posture_read import (
    failure,
    item_row,
    marker,
    posture,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.project_identity import render_item_ref


_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")


def _claim_rows(
    conn: Any,
    item_id: int,
    claim_ids: Optional[Iterable[int]] = None,
) -> list[dict[str, Any]]:
    """Target rows of the item's open claims, or of exactly ``claim_ids``."""
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
    if claim_ids is None:
        column, values = "pc.state", list(_NON_TERMINAL_CLAIM_STATES)
    else:
        column, values = "pc.id", [int(claim_id) for claim_id in claim_ids]
        if not values:
            return []
    value_markers = ", ".join(placeholder for _ in values)
    cursor = conn.execute(
        "SELECT pc.id, pc.state, pt.path_string "
        "FROM path_claims pc "
        "LEFT JOIN path_claim_targets pct ON pct.claim_id = pc.id "
        "LEFT JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pc.owner_kind = 'item' AND pc.owner_item_id = {placeholder} "
        f"AND {column} IN ({value_markers}) "
        "ORDER BY pc.id, pt.path_string",
        (int(item_id), *values),
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
    """Return the selected Dash claim when it already covers the survey."""
    del session_id, integration_target
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
    if not claim_ids:
        joined = ",".join(paths)
        raise ValueError(
            "Selected Dash path-claims posture has no registered coverage. "
            f"Register it first: yoke claims path register --item {render_item_ref(conn, item_id)} "
            f"--paths {joined}"
        )
    if missing:
        joined = ",".join(missing)
        candidate = next(
            (
                claim_id
                for claim_id, state in zip(claim_ids, states)
                if state in {"active", "planned"}
            ),
            claim_ids[0],
        )
        raise ValueError(
            "Selected Dash path-claims coverage is missing surveyed paths: "
            f"{joined}. Widen it: yoke claims path widen --claim-id "
            f"{candidate} --add-paths {joined}"
        )
    return claim_ids[0]


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


def _landed_claim_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """Target rows of the claims released at the item's current landing."""
    from yoke_core.domain.path_claims_landing_boundary import (
        released_claims_for_boundary,
    )

    landed = [claim_id for claim_id, _ in released_claims_for_boundary(conn, item_id)]
    return _claim_rows(conn, item_id, claim_ids=landed)


def completion_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    """Check merged paths against open claims, else the landing's released ones.

    Landing releases the item's claims with reason ``landed``; that released
    coverage still describes what landed. Open claims mean rework, which the
    open coverage alone answers.
    """
    rows = _claim_rows(conn, item_id)
    if rows:
        active = activation_gate(conn, item_id)
        if active is not None:
            return active
        coverage_name = "the open claim"
    else:
        rows = _landed_claim_rows(conn, item_id)
        claim_ids, _, paths = _claim_coverage(rows)
        if not claim_ids or not paths:
            return failure(
                "GATE_DASH_PATH_CLAIM_REQUIRED",
                "Selected Dash path-claims posture has no concrete claim "
                "coverage: no open claim, and no claim released at the "
                "current landing.",
                "Register coverage for the touched files with `yoke claims "
                "path register`, prepare the Dash worktree, then retry.",
            )
        coverage_name = "the claims released at landing"
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_section

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
    _, _, declared = _claim_coverage(rows)
    missing = files_outside_coverage(
        evidence.get("touched_files") or (),
        declared,
    )
    if missing:
        return failure(
            "GATE_DASH_PATH_CLAIM_COVERAGE",
            f"Merged Dash paths fall outside {coverage_name}: " + ", ".join(missing),
            "Widen an open claim through the sanctioned coordination surface; "
            "released coverage cannot widen, so register a claim covering "
            "every touched file instead.",
        )
    return None


__all__ = ["activation_gate", "completion_gate", "ensure_survey_path_claim"]
