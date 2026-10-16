"""Historical item content never enters live conflict candidate hydration."""

import sqlite3

from yoke_core.domain import conflict_survey_blockers as blockers
from yoke_core.domain.conflict_survey import survey_conflicts


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


def test_live_claims_share_postgres_schema_probes_within_one_survey(test_db):
    from runtime.api.domain.path_claim_task_test_support import (
        seed_item_claim,
        seed_target,
    )
    from runtime.api.fixtures.backlog import insert_item

    insert_item(test_db, id=9301, workflow_id="dash")
    insert_item(test_db, id=9302)
    for i in range(50):
        target = seed_target(test_db, item_id=9302, path=f"unrelated/{i}")
        seed_item_claim(test_db, item_id=9302, target_ids=(target,))
    probes = []

    class ObservedConnection:
        def __getattr__(self, name):
            return getattr(test_db, name)

        def execute(self, sql, params=()):
            if "pg_catalog.pg_class" in sql and params == ("path_context_values",):
                probes.append(sql)
            return test_db.execute(sql, params)

    result = survey_conflicts(
        ObservedConnection(), item_id=9301, touch_paths=["src/shared.py"]
    )
    assert result.clear
    assert len(probes) == 1
