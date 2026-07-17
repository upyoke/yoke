"""DB-command guard tests."""

from __future__ import annotations

from yoke_core.domain.lint_db_cmd import run_hook
from yoke_core.domain.lint_db_cmd_test_helpers import (
    _assert_allows,
    _assert_blocks,
    _decision,
    _payload,
)


def test_invalid_payload_allows_by_default() -> None:
    assert run_hook("{not-json") == ""


def test_direct_sqlite_invocation_is_denied() -> None:
    output = run_hook(_payload('sqlite3 "$YOKE_DB" "SELECT 1"'))
    decision = _decision(output)
    assert decision["permissionDecision"] == "deny"
    assert "Do not call sqlite3 directly" in decision["permissionDecisionReason"]


def test_raw_body_write_denial_uses_numeric_item_id() -> None:
    output = run_hook(
        _payload(
            "sh .agents/skills/yoke/scripts/yoke-db.sh "
            "items update YOK-42 body --body-file /tmp/body.md"
        )
    )
    decision = _decision(output)
    assert decision["permissionDecision"] == "deny"
    assert "items update 42" in decision["permissionDecisionReason"]
    assert "YOK-42" not in decision["permissionDecisionReason"]


def test_projects_path_column_blocked_by_static_blocklist() -> None:
    # ``projects.path`` is a curated static-blocklist entry.
    # The removed dynamic ``PRAGMA table_info`` arm is not involved.
    output = run_hook(
        _payload(
            'sh .agents/skills/yoke/scripts/yoke-db.sh '
            'query "SELECT path FROM projects"'
        )
    )
    decision = _decision(output)
    assert decision["permissionDecision"] == "deny"
    assert "Table 'projects' has no column 'path'" in decision["permissionDecisionReason"]


def test_raw_query_module_lifecycle_write_is_denied() -> None:
    decision = _assert_blocks(
        'python3 -m yoke_core.cli.raw_query "UPDATE items SET status = \'done\' WHERE id = 42"'
    )
    assert "items.status" in decision["permissionDecisionReason"]


def test_raw_query_module_ddl_is_denied() -> None:
    decision = _assert_blocks(
        'python3 -m yoke_core.cli.raw_query "ALTER TABLE foo ADD COLUMN bar TEXT"'
    )
    assert "DDL statement" in decision["permissionDecisionReason"]


def test_raw_query_module_readonly_select_is_allowed() -> None:
    _assert_allows(
        'python3 -m yoke_core.cli.raw_query -separator "|" "SELECT id, status FROM items"'
    )


# ---------------------------------------------------------------------------
# false-positive regressions
# ---------------------------------------------------------------------------


def test_postgres_json_path_with_blocked_column_name_allowed() -> None:
    """Wrong column names inside JSON path strings must not trip the static blocklist."""
    # '{context,pr_num}' contains the word "context" which is on the events
    # blocklist, but it is inside a single-quoted string literal — allow.
    assert (
        run_hook(
            _payload(
                "sh .agents/skills/yoke/scripts/yoke-db.sh query "
                "\"SELECT NULLIF(envelope, '')::jsonb #>> '{context,pr_num}' "
                "FROM events WHERE source_type='cli'\""
            )
        )
        == ""
    )
    # Same idea with 'payload' — also a blocked events column name.
    assert (
        run_hook(
            _payload(
                "sh .agents/skills/yoke/scripts/yoke-db.sh query "
                "\"SELECT NULLIF(envelope, '')::jsonb #>> '{payload,branch}' "
                "FROM events\""
            )
        )
        == ""
    )


def test_yok1362_real_blocked_column_still_denied() -> None:
    """The fix must NOT allow actual bare-column references to blocked names."""
    output = run_hook(
        _payload(
            "sh .agents/skills/yoke/scripts/yoke-db.sh query "
            "\"SELECT context FROM events\""
        )
    )
    decision = _decision(output)
    assert decision["permissionDecision"] == "deny"
    assert "context" in decision["permissionDecisionReason"]
