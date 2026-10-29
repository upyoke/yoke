"""Unify old field notes and reflection rows without losing evidence."""

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _add_column_if_not_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
VALUES = "('failed','new','unclear','observation','idea')"


def apply(conn):
    conn.execute("CREATE TEMP TABLE feedback_row_count AS SELECT COUNT(*) AS n FROM ouroboros_entries")
    for name, declaration in (("actor_id", "INTEGER"), ("reporter_email", "TEXT"),
                              ("yoke_version", "TEXT"), ("universe_fingerprint", "TEXT")):
        _add_column_if_not_exists(conn, "ouroboros_entries", name, declaration)
    conn.execute(f"""UPDATE ouroboros_entries SET category = CASE
        WHEN category IN {VALUES} THEN category
        WHEN category IN ('field-note-failed','field-note-new','field-note-unclear',
                          'field-note-observation','field-note-idea') THEN SUBSTR(category,12)
        WHEN category IN ('friction','problem') THEN 'failed'
        WHEN category='game-changing-idea' THEN 'idea'
        ELSE 'observation' END""")
    conn.execute("ALTER TABLE ouroboros_entries DROP CONSTRAINT IF EXISTS feedback_category_valid")
    conn.execute(f"ALTER TABLE ouroboros_entries ADD CONSTRAINT feedback_category_valid CHECK (category IN {VALUES})")


def invariants(conn):
    assert conn.execute(f"SELECT COUNT(*) FROM ouroboros_entries WHERE category NOT IN {VALUES}").fetchone()[0] == 0
    if conn.execute("SELECT to_regclass('pg_temp.feedback_row_count')").fetchone()[0] is not None:
        before = conn.execute("SELECT n FROM feedback_row_count").fetchone()[0]
        after = conn.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
        assert before == after, "feedback_row_count_changed: retain all original notes"
        conn.execute("DROP TABLE feedback_row_count")

# Retired protocol history: these names are never registered or executed.
RETIRED_FUNCTION_FAMILIES = {
    "ouroboros.entry": ("insert", "list", "get"),
    "ouroboros.reflection": ("capture",),
}
RETIRED_HOOKS = ("yoke_core.domain.reflection_capture_hook",)
RETIRED_EVENTS = (
    "ReflectionCaptureHookFired", "ReflectionCaptureHookUnhandled",
    "ReflectionCapturePersistFailed", "ReflectionMarkerParseFailed",
)
