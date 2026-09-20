"""Check 15b: lifecycle SQL a command executes versus SQL it carries as text.

Editing a file whose contents quote lifecycle SQL is ordinary implementation
work. The guard exists to stop a live mutation, so the question it has to
answer is whether the inline program hands that SQL to a database, not
whether the characters appear in the command body.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.lint_db_cmd_test_helpers import _assert_allows, _assert_blocks

# The shape a source edit actually takes: read the file, substitute text, write
# it back. The lifecycle SQL belongs to the test case being authored, and so
# does the ``execute(`` that would otherwise read as a live mutation.
AUTHORS_A_TEST_CASE = '''python3 - <<'PY'
from pathlib import Path
p = Path("runtime/api/domain/test_steering_fleet_report_detectors.py")
t = p.read_text()
old = "    # landing fixture"
new = """    cur.execute(
        "UPDATE items SET merged_at = %s WHERE id = 1", (landed_at,),
    )"""
p.write_text(t.replace(old, new))
PY'''

WRITES_AN_EMITTER_FIXTURE = '''python3 - <<'PY'
from pathlib import Path
p = Path("runtime/api/domain/test_emitter_contract.py")
body = 'conn.execute("INSERT INTO events (event_name) VALUES (%s)", (name,))'
p.write_text(p.read_text().replace("# emitter fixture", body))
PY'''

REPLACES_A_DELETE_FIXTURE = '''python3 - <<'PY'
from pathlib import Path
p = Path("runtime/api/domain/test_epic_task_cleanup.py")
p.write_text(
    p.read_text().replace(
        "# cleanup fixture",
        'cur.execute("DELETE FROM epic_tasks WHERE epic_id = 1")',
    )
)
PY'''


@pytest.mark.parametrize(
    "command",
    [AUTHORS_A_TEST_CASE, WRITES_AN_EMITTER_FIXTURE, REPLACES_A_DELETE_FIXTURE],
)
def test_lifecycle_sql_written_into_a_file_is_not_a_mutation(command: str) -> None:
    """These programs call only read_text / replace / write_text."""
    _assert_allows(command)


# The same statements, this time handed to a live cursor.
EXECUTES_ITEM_STATUS = '''python3 - <<'PY'
import psycopg
conn = psycopg.connect(DSN)
conn.execute("UPDATE items SET status = 'done' WHERE id = 1")
PY'''

EXECUTES_AN_EVENT_INSERT = '''python3 - <<'PY'
import psycopg
with psycopg.connect(DSN) as conn:
    conn.execute("INSERT INTO events (event_name) VALUES ('Fabricated')")
PY'''

EXECUTES_SQL_HELD_IN_A_VARIABLE = '''python3 - <<'PY'
import psycopg
sql = "UPDATE epic_tasks SET status = 'done' WHERE epic_id = 1"
conn = psycopg.connect(DSN)
conn.cursor().execute(sql)
PY'''

EXECUTES_AN_F_STRING = '''python3 - <<'PY'
import psycopg
conn = psycopg.connect(DSN)
conn.execute(f"UPDATE items SET status = '{target}' WHERE id = {item_id}")
PY'''

EXECUTES_THROUGH_EXECUTESCRIPT = '''python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("/tmp/copy.db")
conn.executescript("UPDATE items SET deploy_stage = 'shipped' WHERE id = 1")
PY'''


@pytest.mark.parametrize(
    "command",
    [
        EXECUTES_ITEM_STATUS,
        EXECUTES_AN_EVENT_INSERT,
        EXECUTES_SQL_HELD_IN_A_VARIABLE,
        EXECUTES_AN_F_STRING,
        EXECUTES_THROUGH_EXECUTESCRIPT,
    ],
)
def test_lifecycle_sql_handed_to_a_cursor_is_still_denied(command: str) -> None:
    _assert_blocks(command)


def test_sql_reaching_a_call_through_an_unreadable_expression_stays_denied() -> None:
    """When the SQL arrives through an expression this layer cannot read, the
    guard keeps the conservative whole-payload scan rather than allowing."""
    _assert_blocks(
        """python3 - <<'PY'
import psycopg
conn = psycopg.connect(DSN)
conn.execute(STATEMENTS["retire"] % "UPDATE items SET status = 'done'")
PY"""
    )


def test_an_unparseable_payload_keeps_the_conservative_text_scan() -> None:
    """A payload that does not parse must not become an allow."""
    _assert_blocks(
        """python3 - <<'PY'
conn.execute("UPDATE items SET status = 'done'" if
PY"""
    )
