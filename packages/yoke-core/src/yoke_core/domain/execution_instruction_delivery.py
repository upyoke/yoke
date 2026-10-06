"""Delivery settings and stage-bucket matching for execution instructions."""

from __future__ import annotations

import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, model_validator

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_execution_instructions_schema import (
    WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE,
)

StageBucket = Literal[
    "idea", "planning", "refined", "implementing", "reviewing", "implemented", "release"
]
DeliveryPoint = Literal["before_creation", "on_every_read", "when_entering_stage"]
DELIVERY_FIELDS = (
    "before_creation",
    "on_every_read",
    "when_entering_stage",
    "stage_buckets",
)


class InstructionDelivery(BaseModel):
    before_creation: bool = True
    on_every_read: bool = True
    when_entering_stage: bool = False
    stage_buckets: list[StageBucket] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_delivery(self):
        if not (self.before_creation or self.on_every_read or self.when_entering_stage):
            raise ValueError(
                "delivery_point_required: select Before creation, On every read, or When entering stage"
            )
        if self.when_entering_stage and not self.stage_buckets:
            raise ValueError(
                "stage_bucket_required: select at least one stage bucket for When entering stage"
            )
        self.stage_buckets = list(dict.fromkeys(self.stage_buckets))
        return self


def delivery_options() -> dict[str, Any]:
    """The bucket vocabulary and new-instruction defaults editors must offer."""
    return {
        "stage_buckets": list(get_args(StageBucket)),
        "defaults": InstructionDelivery().model_dump(),
    }


def delivery_from_row(row) -> dict[str, Any]:
    return dict(
        zip(
            DELIVERY_FIELDS,
            [bool(row[0]), bool(row[1]), bool(row[2]), json.loads(row[3])],
        )
    )


def save_delivery(conn, instruction_id: int, changes: dict[str, Any] | None) -> None:
    if not changes:
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {', '.join(DELIVERY_FIELDS)} FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} WHERE id = {p}{lock}",
        (instruction_id,),
    ).fetchone()
    delivery = InstructionDelivery.model_validate({**delivery_from_row(row), **changes})
    conn.execute(
        f"UPDATE {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} SET "
        + ", ".join(f"{field} = {p}" for field in DELIVERY_FIELDS)
        + f" WHERE id = {p}",
        (
            int(delivery.before_creation),
            int(delivery.on_every_read),
            int(delivery.when_entering_stage),
            json.dumps(delivery.stage_buckets),
            instruction_id,
        ),
    )


def matches_delivery(
    instruction: dict, point: DeliveryPoint, bucket: str | None
) -> bool:
    at_stage = (
        instruction["when_entering_stage"] and bucket in instruction["stage_buckets"]
    )
    if point == "on_every_read":
        return instruction["on_every_read"] or at_stage
    if point == "when_entering_stage":
        return bool(at_stage)
    return instruction["before_creation"]


def item_stage_bucket(conn, item_id: int, stage_id: str | None = None) -> str | None:
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if stage_id is None:
        stage_id = conn.execute(
            f"SELECT status FROM items WHERE id = {p}", (item_id,)
        ).fetchone()[0]
    stage = load_item_workflow_runtime(conn, item_id).stage(stage_id)
    return str(stage["board_bucket"]) if stage else None


def item_instructions(
    item_id: int,
    *,
    delivery_point: DeliveryPoint = "on_every_read",
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_execution_instructions import resolve_for_item

    with connect() as conn:
        return resolve_for_item(
            conn, item_id, delivery_point=delivery_point, stage_id=stage_id
        )
