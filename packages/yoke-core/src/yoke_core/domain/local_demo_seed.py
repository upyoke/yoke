"""Local-universe demo data seeding for installer smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect


@dataclass(frozen=True)
class DemoItemSpec:
    title: str
    priority: str
    spec: str
    workflow: str = "issue"


DEFAULT_DEMO_ITEMS: tuple[DemoItemSpec, ...] = (
    DemoItemSpec(
        "Local installer smoke first item",
        "medium",
        "Demo item seeded by the local installer smoke. Done when it shows "
        "on the board and can be claimed.",
    ),
    DemoItemSpec(
        "Local installer smoke second item",
        "low",
        "Second demo item seeded by the local installer smoke. Done when the "
        "board lists it below the first item.",
    ),
    DemoItemSpec(
        "Local smoke dashboard check",
        "high",
        "Demo item seeded by the local installer smoke. Done when the local "
        "dashboard shows it among the ready work.",
    ),
)


class LocalDemoSeedError(RuntimeError):
    """Demo seed data could not be created."""


def seed_demo_items(
    *,
    project: Optional[str] = None,
    count: int = len(DEFAULT_DEMO_ITEMS),
) -> dict[str, Any]:
    """Create local smoke items through the registered harness-skill path."""
    if count < 1:
        raise LocalDemoSeedError("count must be at least 1")
    specs = _selected_specs(count)
    source_actor = _local_human_actor_id()
    created: list[dict[str, Any]] = []

    from yoke_core.domain.backlog_create_op import execute_create

    for spec in specs:
        result = execute_create(
            title=spec.title,
            workflow=spec.workflow,
            priority=spec.priority,
            project=project,
            source=str(source_actor),
            owner=str(source_actor),
            entry_surface="harness_skill",
            spec=spec.spec,
        )
        if not result.get("success"):
            raise LocalDemoSeedError(str(result.get("error") or "item create failed"))
        created.append(
            {
                "public_ref": result.get("public_ref"),
                "title": spec.title,
                "priority": spec.priority,
            }
        )
    return {
        "ok": True,
        "project": project,
        "source_actor_id": source_actor,
        "items": created,
        "next_step": (
            "run `yoke board rebuild --print --no-pager` in the project checkout"
        ),
    }


def _selected_specs(count: int) -> list[DemoItemSpec]:
    out: list[DemoItemSpec] = []
    while len(out) < count:
        out.extend(DEFAULT_DEMO_ITEMS)
    return out[:count]


def _local_human_actor_id() -> int:
    from yoke_core.domain import actors

    conn = connect()
    try:
        local_human = actors.seed_canonical_human(conn)
        conn.commit()
        return int(local_human)
    finally:
        conn.close()


__all__ = [
    "DEFAULT_DEMO_ITEMS",
    "LocalDemoSeedError",
    "seed_demo_items",
]
