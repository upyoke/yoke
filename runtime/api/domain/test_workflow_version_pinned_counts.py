"""How many items pin each stored version.

Version history otherwise reads as a flat list where every older row looks
equally disposable. The count is what separates a version live work is running
against from one that is merely readable, so it decides whether selecting a
different version is routine or disruptive.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.workflow_registry import (
    list_current_workflows,
    publish_workflow_version,
)
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)


def _versions(conn, workflow_id: str = "issue") -> dict[int, dict]:
    row = next(
        row for row in list_current_workflows(conn) if row["id"] == workflow_id
    )
    return {int(entry["version"]): entry for entry in row["versions"]}


def _pin(conn, item_id: int, version_id: int, workflow_id: str = "issue"):
    """Create an item pinned to one specific stored version.

    The fixture pins whatever is current, which is the right default and the
    wrong thing for asserting per-version counts, so the pin is moved
    afterwards rather than by fighting the fixture's own invariants.
    """
    insert_item(conn, id=item_id, workflow_id=workflow_id)
    conn.execute(
        "UPDATE items SET workflow_version_id = %s WHERE id = %s",
        (version_id, item_id),
    )
    conn.commit()


def test_a_version_no_item_pins_counts_zero(test_db):
    for entry in _versions(test_db).values():
        assert entry["pinned_item_count"] == 0


def test_each_version_counts_only_its_own_items(test_db):
    edited = builtin_workflow_definition("issue")["definition"]
    edited["entry_surfaces"] = [
        surface for surface in edited["entry_surfaces"]
        if surface != "promotion"
    ]
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=edited,
    )
    before = _versions(test_db)
    older = before[int(published["version"]) - 1]
    newer = before[int(published["version"])]

    _pin(test_db, 4001, int(older["id"]))
    _pin(test_db, 4002, int(newer["id"]))
    _pin(test_db, 4003, int(newer["id"]))

    after = _versions(test_db)
    assert after[int(older["version"])]["pinned_item_count"] == 1
    assert after[int(newer["version"])]["pinned_item_count"] == 2


def test_another_workflow_s_items_do_not_leak_into_the_count(test_db):
    """Counted by version row, so two workflows cannot inflate each other."""
    epic_version = int(
        next(
            row for row in list_current_workflows(test_db)
            if row["id"] == "epic"
        )["current_version_id"]
    )
    _pin(test_db, 4101, epic_version, workflow_id="epic")

    for entry in _versions(test_db, "issue").values():
        assert entry["pinned_item_count"] == 0
    epic = _versions(test_db, "epic")
    assert sum(
        entry["pinned_item_count"] for entry in epic.values()
    ) == 1
