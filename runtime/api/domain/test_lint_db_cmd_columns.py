"""DB-command guard checks for wrong SQL column names."""

from __future__ import annotations

import pytest

from yoke_core.domain.lint_db_cmd_test_helpers import (
    _assert_allows,
    _assert_blocks,
)


# ---------------------------------------------------------------------------
# Check 8 — wrong SQL column names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sh scripts/yoke-db.sh query \"SELECT type FROM events WHERE source='hook'\"",
        "sh scripts/yoke-db.sh query \"SELECT context FROM events WHERE event_name='foo'\"",
        'sh scripts/yoke-db.sh query "SELECT timestamp FROM events LIMIT 1"',
        'sh scripts/yoke-db.sh query "SELECT entry FROM ouroboros_entries LIMIT 5"',
        'sh scripts/yoke-db.sh query "SELECT item_id, task_number FROM epic_tasks WHERE epic_id=1"',
        'sh scripts/yoke-db.sh query "SELECT item_id FROM epic_tasks"',
        'sh scripts/yoke-db.sh query "SELECT item_id FROM shepherd_verdicts"',
        'sh scripts/yoke-db.sh query "SELECT item_id FROM deployment_runs WHERE id=1"',
        'sh scripts/yoke-db.sh query "SELECT id FROM deployment_run_items WHERE run_id=1"',
        "sh scripts/yoke-db.sh query \"SELECT requirement_id FROM qa_runs WHERE verdict='pass'\"",
        "sh scripts/yoke-db.sh query \"SELECT req_id FROM qa_runs WHERE verdict='pass'\"",
    ],
)
def test_yok870_wrong_sql_columns_blocked(command: str) -> None:
    _assert_blocks(command)


def test_yok1106_wrong_events_outcome_suggests_event_outcome() -> None:
    decision = _assert_blocks(
        "sh scripts/yoke-db.sh query \"SELECT outcome FROM events WHERE event_name='foo'\""
    )
    assert "event_outcome" in decision["permissionDecisionReason"], (
        "correction hint should mention event_outcome"
    )


def test_events_json_column_advice_is_postgres_native() -> None:
    decision = _assert_blocks(
        "sh scripts/yoke-db.sh query \"SELECT context FROM events WHERE event_name='foo'\""
    )
    reason = decision["permissionDecisionReason"]
    assert "Postgres #>> operator" in reason
    assert "json_extract" not in reason


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh query "SELECT event_name, source_type, created_at FROM events LIMIT 5"',
        'sh scripts/yoke-db.sh query "SELECT body FROM ouroboros_entries LIMIT 5"',
        'sh scripts/yoke-db.sh query "SELECT id, current_stage FROM deployment_runs LIMIT 5"',
        'sh scripts/yoke-db.sh query "SELECT run_id, item_id FROM deployment_run_items LIMIT 5"',
        'sh scripts/yoke-db.sh query "SELECT qa_requirement_id, verdict FROM qa_runs LIMIT 5"',
        "sh scripts/yoke-db.sh query \"SELECT spec FROM items WHERE status='active'\"",
        'echo "events type"',
        'sh scripts/yoke-db.sh query "SELECT timestamp FROM events" # lint:no-column-check',
    ],
)
def test_yok870_valid_columns_and_bypass_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Static-only column validation
# ---------------------------------------------------------------------------
#
# The dynamic ``PRAGMA table_info`` arm (legacy "Check 8b") was removed in the
# Postgres-native cleanup: it only ever fired when ``YOKE_DB`` was an on-disk
# SQLite file, which never happens once Yoke authority is Postgres. The
# curated static blocklist (Check 8) is the live coverage; a wrong column that
# is not on that blocklist is no longer schema-validated.


def test_unknown_column_not_in_blocklist_is_allowed() -> None:
    # No dynamic schema probe: a wrong column that is not on the static
    # blocklist passes, while a blocklisted wrong column is still caught.
    _assert_allows(
        'sh scripts/yoke-db.sh query "SELECT fake_column FROM items WHERE id=1"'
    )
    _assert_blocks(
        'sh scripts/yoke-db.sh query "SELECT timestamp FROM events LIMIT 1"'
    )


# ---------------------------------------------------------------------------
# AS alias stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sh scripts/yoke-db.sh query "
        "\"SELECT NULLIF(envelope, '')::jsonb #>> '{tool_name}' as tool, "
        "NULLIF(envelope, '')::jsonb #>> '{anomaly}' as anomaly "
        "FROM events WHERE event_name='HarnessToolCallCompleted'\"",
        "sh scripts/yoke-db.sh query \"SELECT id as item_id FROM items WHERE status='active'\"",
        "sh scripts/yoke-db.sh query "
        "\"SELECT NULLIF(envelope, '')::jsonb #>> '{error_summary}' as error_summary, "
        "event_name as name FROM events LIMIT 10\"",
    ],
)
def test_yok1106_as_alias_stripping_allowed(command: str) -> None:
    _assert_allows(command)


# ---------------------------------------------------------------------------
# Quoted string stripping (keywords in titles)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'sh scripts/yoke-db.sh items add --project yoke "Title mentioning sqlite3 engine"',
        'sh scripts/yoke-db.sh items add --project yoke "Fix backlog-registry.sh error handling"',
        'sh scripts/yoke-db.sh items add --project yoke "DB error messages swallowed by backlog-registry.sh -- no stderr propagation through yoke-db.sh"',
        'sh scripts/yoke-db.sh items add --project yoke "Fix claude agent config issue"',
        'sh scripts/yoke-db.sh items update 42 title "sqlite3 migration issues"',
    ],
)
def test_yok919_keywords_in_title_strings_allowed(command: str) -> None:
    _assert_allows(command)


@pytest.mark.parametrize(
    "command",
    [
        'sqlite3 yoke.db "SELECT * FROM items"',
        'sh backlog-registry.sh add "item"',
        "sh scripts/yoke-db.sh query \"SELECT * FROM items WHERE status != 'done'\"",
        'sh scripts/yoke-db.sh query "SELECT timestamp FROM events LIMIT 1"',
    ],
)
def test_yok919_true_positives_still_blocked(command: str) -> None:
    _assert_blocks(command)
