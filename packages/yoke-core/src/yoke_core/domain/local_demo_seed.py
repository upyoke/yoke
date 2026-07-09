"""Local-universe demo data seeding for installer smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect


@dataclass(frozen=True)
class DemoItemSpec:
    title: str
    priority: str
    item_type: str = "issue"


DEFAULT_DEMO_ITEMS: tuple[DemoItemSpec, ...] = (
    DemoItemSpec("Local installer smoke first item", "medium"),
    DemoItemSpec("Local installer smoke second item", "low"),
    DemoItemSpec("Local smoke dashboard check", "high"),
)


class LocalDemoSeedError(RuntimeError):
    """Demo seed data could not be created."""


def seed_demo_items(
    *,
    project: Optional[str] = None,
    count: int = len(DEFAULT_DEMO_ITEMS),
) -> dict[str, Any]:
    """Create local smoke items through the normal idea-intake create path."""
    if count < 1:
        raise LocalDemoSeedError("count must be at least 1")
    specs = _selected_specs(count)
    source_actor = _local_human_actor_id()
    created: list[dict[str, Any]] = []

    from yoke_core.domain.backlog_create_op import execute_create

    for spec in specs:
        result = execute_create(
            title=spec.title,
            item_type=spec.item_type,
            priority=spec.priority,
            project=project,
            source=str(source_actor),
            owner=str(source_actor),
            provenance="idea",
            rebuild_board=False,
        )
        if not result.get("success"):
            raise LocalDemoSeedError(str(result.get("error") or "item create failed"))
        created.append({
            "item_id": result.get("item_id"),
            "item_ref": result.get("item_ref"),
            "title": spec.title,
            "priority": spec.priority,
        })
    return {
        "ok": True,
        "project": project,
        "source_actor_id": source_actor,
        "items": created,
        "next_step": "run `yoke board rebuild --print` in the project checkout",
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
        _system_actor, local_human = actors.seed_canonical_actors(conn)
        conn.commit()
        return int(local_human)
    finally:
        conn.close()


__all__ = [
    "DEFAULT_DEMO_ITEMS",
    "LocalDemoSeedError",
    "seed_demo_items",
]
