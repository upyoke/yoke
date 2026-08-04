"""Remove migration-apply stages from deployment flows.

Applying a migration stopped being a deployment stage: a database is brought
up to its code by the boot converge that starts the container, not by a step
some flow remembers to include. The stage kind is therefore retired, and the
live flow rows that still carry one have to lose it — a flow whose first stage
names a kind the runner no longer dispatches would halt at stage 0 rather than
deploy.

Ordering matters and is why this sits ahead of the stage-vocabulary entry:
that one revalidates every flow's stage array, and validation rejects the
retired kind. Stripping has to happen first or the later entry fails on data
this one was going to clean.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.flow_validation import validate_stages

RETIRED_STAGE_KIND = "migration_apply"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stages(raw: Any, *, subject: str) -> list[Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{subject} stages is not valid JSON") from exc
    if not isinstance(value, list):
        raise AssertionError(f"{subject} stages must be a JSON array")
    return value


def _without_retired_stages(stages: list[Any]) -> list[Any]:
    return [
        stage
        for stage in stages
        if not (isinstance(stage, dict) and stage.get("kind") == RETIRED_STAGE_KIND)
    ]


def apply(conn: Any) -> None:
    """Strip retired stages, writing only the flows that actually carry one."""
    marker = _marker(conn)
    rows = conn.execute("SELECT id, stages FROM deployment_flows ORDER BY id").fetchall()
    for row in rows:
        original = _stages(row[1], subject=f"deployment flow {row[0]}")
        remaining = _without_retired_stages(copy.deepcopy(original))
        if remaining == original:
            continue
        if not remaining:
            raise AssertionError(
                f"deployment flow {row[0]} would be left with no stages; "
                "a flow that was only a migration step needs an operator "
                "decision, not a silent empty definition"
            )
        conn.execute(
            f"UPDATE deployment_flows SET stages={marker} WHERE id={marker}",
            (json_helper.dumps_compact(remaining), row[0]),
        )


def invariants(conn: Any) -> None:
    """No live flow retains the retired kind, and every array still validates."""
    for row in conn.execute(
        "SELECT id, stages FROM deployment_flows ORDER BY id"
    ).fetchall():
        stages = _stages(row[1], subject=f"deployment flow {row[0]}")
        for stage in stages:
            if isinstance(stage, dict) and stage.get("kind") == RETIRED_STAGE_KIND:
                raise AssertionError(
                    f"deployment flow {row[0]} retains a {RETIRED_STAGE_KIND} stage"
                )
        validate_stages(json_helper.dumps_compact(stages))


__all__ = ["RETIRED_STAGE_KIND", "apply", "invariants"]
