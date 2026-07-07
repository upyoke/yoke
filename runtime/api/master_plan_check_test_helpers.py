"""Shared helpers for test_master_plan_check*.py modules.

Pure helpers (no pytest fixtures) — safe to import from any test module
without triggering pytest fixture-discovery side effects. The naming
convention `<stem>_test_helpers.py` keeps pytest from collecting an
empty test module.
"""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb

# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

POSITIVE_PLAN = """# Yoke Master Plan

Some preamble.

## 5. Backlog By Generation

### 5.2 Current frontier

#### Landed

1. `YOK-100` — `Some landed foundation work`

#### Remaining frontier

1. `Define the first frontier enabler` (YOK-200)

2. `Build on first enabler` (YOK-201)

3. `Ship the dependent slice` (YOK-202)
"""


MISSING_SECTION_PLAN = """# Yoke Master Plan

This plan has no backlog section at all.

## 2. State A

Some content.
"""


PROSE_PLAN = """# Plan

## 5. Backlog By Generation

#### Remaining frontier

1. `Ship integrator` (YOK-500)
2. `Ship dependent` (YOK-501)

And in narrative prose: `YOK-500` is a prerequisite slice for `YOK-501`.

Another sentence: `YOK-501` depends on `YOK-500` before it can start.

Ambiguous: `YOK-500`, `YOK-501`, and `YOK-502` must not outrun each other.
"""


def make_items_db(rows: list[tuple[int, str]]):
    """Return a disposable-DB row-shape double for ``lookup_statuses`` tests.

    Mints a minimal-schema disposable Postgres test database (dropped when
    the connection closes). It mirrors the public-ref resolution shape the
    validator routes through (``yok_n_parser.parse_item_id``): a
    ``projects`` row carrying the ``YOK`` prefix plus per-project
    ``project_sequence`` columns (backfilled ``sequence = id``, the
    cutover convention this fixture data predates).
    """
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    pg_testdb.drop_database_on_close(conn, name)
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
        "name TEXT, public_item_prefix TEXT)"
    )
    conn.execute(
        "INSERT INTO projects VALUES (1, 'yoke', 'Yoke', 'YOK')"
    )
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT, "
        "project_id INTEGER NOT NULL DEFAULT 1, project_sequence INTEGER)"
    )
    for item_id, item_status in rows:
        conn.execute(
            "INSERT INTO items (id, status, project_id, project_sequence) "
            "VALUES (%s, %s, 1, %s)",
            (item_id, item_status, item_id),
        )
    conn.commit()
    return conn
