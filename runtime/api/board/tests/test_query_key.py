"""Board query keys ignore layout without erasing SQL content."""

from __future__ import annotations

import pytest

from yoke_contracts.board.data import BOARD_DATA_VERSION, ReplayBoardDB, entry_key
from yoke_contracts.board.query_key import canonicalize_sql


def test_layout_only_changes_share_one_key() -> None:
    multiline = """
        SELECT scope,
               session_id
          FROM work_claims
         WHERE scope = %s
    """
    wrapped = "SELECT scope, session_id FROM work_claims WHERE scope = %s"

    assert entry_key("query", multiline, ['{"item_id":42}']) == entry_key(
        "query", wrapped, ['{"item_id":42}']
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("SELECT 'a  b'", "SELECT 'a b'"),
        ("SELECT 'a''  b'", "SELECT 'a'' b'"),
        ('SELECT "a  b"', 'SELECT "a b"'),
        ("SELECT $$a  b$$", "SELECT $$a b$$"),
        ("SELECT $body$a  b$body$", "SELECT $body$a b$body$"),
        ("SELECT 1 /* a  b */", "SELECT 1 /* a b */"),
        ("SELECT 1 -- a  b\n", "SELECT 1 -- a b\n"),
    ],
)
def test_literal_and_comment_whitespace_remains_significant(
    left: str,
    right: str,
) -> None:
    assert entry_key("query", left, None) != entry_key("query", right, None)


def test_line_comment_terminator_cannot_collide_with_comment_text() -> None:
    continued_sql = "SELECT 1 -- explanation\nFROM items"
    commented_out_sql = "SELECT 1 -- explanation FROM items"

    assert canonicalize_sql(continued_sql) != canonicalize_sql(commented_out_sql)


def test_nested_block_comment_is_preserved_as_one_protected_span() -> None:
    spaced = "SELECT 1 /* outer /* inner  text */ end */"
    compact = "SELECT 1 /* outer /* inner text */ end */"

    assert entry_key("query", spaced, None) != entry_key("query", compact, None)


def test_real_sql_and_interpolated_filter_changes_keep_distinct_keys() -> None:
    active = "SELECT * FROM coordination_leases WHERE released_at IS NULL"
    all_rows = "SELECT * FROM coordination_leases WHERE TRUE"

    assert entry_key("query_quiet", active, None) != entry_key(
        "query_quiet", all_rows, None
    )


def test_payload_replay_uses_the_same_canonical_sql_as_recording() -> None:
    payload = {
        "version": BOARD_DATA_VERSION,
        "entries": [
            {
                "kind": "query_quiet",
                "sql": "SELECT scope,\n       session_id FROM work_claims",
                "params": None,
                "rows": [['{"item_id":42}', "session-1"]],
            }
        ],
    }

    replay = ReplayBoardDB.from_payload(payload)

    assert replay.query_quiet("  SELECT scope, session_id\n  FROM work_claims  ") == [
        ('{"item_id":42}', "session-1")
    ]
