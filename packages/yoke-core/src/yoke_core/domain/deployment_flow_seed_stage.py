"""Helpers that converge existing deployment flows onto seed stage changes."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


def ensure_seed_stage(
    conn: Any,
    *,
    seed_flows: Sequence[Mapping[str, Any]],
    flow_id: str,
    stage_name: str,
    before_stage: str,
) -> None:
    """Insert or replace a seed-owned stage in an existing flow."""
    seed_flow = next((flow for flow in seed_flows if flow["id"] == flow_id), None)
    if seed_flow is None:
        return
    try:
        seed_stages = json.loads(str(seed_flow["stages"]))
    except (json.JSONDecodeError, TypeError, KeyError):
        return
    seed_stage = next(
        (
            stage for stage in seed_stages
            if isinstance(stage, dict) and stage.get("name") == stage_name
        ),
        None,
    )
    if seed_stage is None:
        return
    row = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id = %s",
        (flow_id,),
    ).fetchone()
    if row is None:
        return
    raw_live = row[0] if not hasattr(row, "keys") else row["stages"]
    try:
        live_stages = json.loads(raw_live) if raw_live else []
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(live_stages, list):
        return
    existing_index = next(
        (
            index for index, stage in enumerate(live_stages)
            if isinstance(stage, dict) and stage.get("name") == stage_name
        ),
        None,
    )
    if existing_index is not None:
        if live_stages[existing_index] == seed_stage:
            return
        merged = [*live_stages]
        merged[existing_index] = seed_stage
        conn.execute(
            "UPDATE deployment_flows SET stages = %s WHERE id = %s",
            (json.dumps(merged), flow_id),
        )
        return
    insert_at = next(
        (
            index for index, stage in enumerate(live_stages)
            if isinstance(stage, dict) and stage.get("name") == before_stage
        ),
        len(live_stages),
    )
    merged = [*live_stages[:insert_at], seed_stage, *live_stages[insert_at:]]
    conn.execute(
        "UPDATE deployment_flows SET stages = %s WHERE id = %s",
        (json.dumps(merged), flow_id),
    )


def ensure_seed_metadata(
    conn: Any,
    *,
    seed_flows: Sequence[Mapping[str, Any]],
    flow_ids: Sequence[str],
) -> None:
    """Converge owned seed-flow descriptions onto the current seed text."""
    wanted = set(flow_ids)
    for flow in seed_flows:
        flow_id = str(flow.get("id", ""))
        if flow_id not in wanted:
            continue
        conn.execute(
            "UPDATE deployment_flows "
            "SET description = %s, done_description = %s "
            "WHERE id = %s",
            (
                flow.get("description"),
                flow.get("done_description"),
                flow_id,
            ),
        )
