"""Historical item content never enters live conflict candidate hydration."""

import sqlite3

from yoke_core.domain import conflict_survey_blockers as blockers


def test_historical_content_is_filtered_before_hydration(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER, "
        "status TEXT, frozen INTEGER, spec TEXT)"
    )
    budget = "## File Budget\n- `src/shared.py`\n"
    conn.executemany(
        "INSERT INTO items VALUES (?, 1, ?, ?, ?)",
        [
            (1, "implementing", 0, ""),
            (2, "implementing", 0, budget),
            (3, "blocked", None, budget),
            *[
                (
                    i + 10,
                    ("done", "cancelled", "stopped", "implementing")[i % 4],
                    int(i % 4 == 3),
                    budget + "x" * 8000,
                )
                for i in range(4000)
            ],
        ],
    )
    hydrated = []
    original = blockers._dict_rows

    def observe(cursor):
        rows = original(cursor)
        if "file_budget_section" in [column[0] for column in cursor.description]:
            hydrated.extend(rows)
        return rows

    monkeypatch.setattr(blockers, "_dict_rows", observe)
    contacts = blockers._item_coordination_blockers(
        conn,
        item={"id": 1, "project_id": 1},
        touch_paths=("src/shared.py",),
        integration_target="main",
    )
    assert {row.owner_item_id for row in contacts} == {2, 3}
    assert {row.kind for row in contacts} == {"frontier_scope"}
    assert len(hydrated) == 2
    assert sum(len(row["spec"].encode()) for row in hydrated) < 100
