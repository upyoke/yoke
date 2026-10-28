# The imported fixture must keep its public name so pytest can inject it.
# ruff: noqa: F811
"""The scheduler never selects a step a new worker could not advance.

Every workflow binds a skill to its release stage, so a landed item waiting
only on its next release ranks as runnable. Selecting it handed a new worker
an item whose remaining work belonged to the release.
"""

from __future__ import annotations

from yoke_core.domain.scheduler import compute_schedule
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    _workflow_pin,
    scheduler_db,
)


def _dash_item(conn, item_id: int, status: str, priority: str, merged_at=None):
    workflow_id, workflow_version_id = _workflow_pin(conn, "dash")
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, "
        "priority, project_id, project_sequence, created_at, updated_at, source, "
        "frozen, spec, merged_at) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, "
        "'2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user', 0, %s, %s)",
        (
            item_id,
            f"Dash {item_id}",
            workflow_id,
            workflow_version_id,
            status,
            priority,
            item_id,
            "# Spec\n\nA real spec body.",
            merged_at,
        ),
    )


def test_a_landed_release_item_is_never_the_selected_step(scheduler_db):
    conn = scheduler_db["conn"]
    conn.execute("UPDATE items SET frozen=1")
    _dash_item(conn, 20, "release", "high", merged_at="2026-03-02T00:00:00Z")
    _dash_item(conn, 21, "idea", "low")
    conn.commit()

    result = compute_schedule(conn, project_scope=["yoke"], emit_events=False)

    assert [step.item_id for step in result.ranked_steps][:1] == [20]
    assert result.selected_step is not None
    assert result.selected_step.item_id == 21
    assert [step.item_id for step in result.staffable_steps] == [21]
