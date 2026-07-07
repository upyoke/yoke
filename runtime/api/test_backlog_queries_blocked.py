"""Coverage for the blocked-flag query helpers.

Mirrors :mod:`runtime.api.test_backlog_queries_freeze` for the new
``items.blocked`` flag. Verifies:

- ``is_blocked`` coercion across SQLite NULL / int / bool / string values.
- ``sql_blocked_filter`` produces the same compatibility shape as
  ``sql_frozen_filter`` (``col = 1`` for blocked, ``(col IS NULL OR col = 0)``
  for not blocked).
- ``ItemFilter.blocked`` and ``ItemFilter.exclude_blocked`` flow through
  ``build_where_clause``.
- ``classify_item_state`` returns the new ``"blocked"`` category for
  flag-set items independently of ``status`` and orthogonally to
  ``frozen``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.queries import (
    ItemFilter,
    build_where_clause,
    classify_item_state,
    is_blocked,
    is_frozen,
    sql_blocked_filter,
    sql_frozen_filter,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        (0, False),
        (1, True),
        ("0", False),
        ("1", True),
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        ("anything-else", False),
    ],
)
def test_is_blocked_coerces(value, expected):
    assert is_blocked(value) is expected


def test_sql_blocked_filter_set_matches_frozen_shape():
    assert sql_blocked_filter(True, col="i.blocked") == "i.blocked = 1"
    assert sql_blocked_filter(True) == "blocked = 1"
    assert sql_frozen_filter(True) == "frozen = 1"


def test_sql_blocked_filter_unset_matches_frozen_shape():
    assert (
        sql_blocked_filter(False, col="i.blocked")
        == "(i.blocked IS NULL OR i.blocked = 0)"
    )
    assert sql_blocked_filter(False) == "(blocked IS NULL OR blocked = 0)"


def test_item_filter_blocked_emits_set_clause():
    where, params = build_where_clause(ItemFilter(blocked=True))
    assert "blocked = 1" in where
    assert params == []


def test_item_filter_blocked_emits_unset_clause():
    where, params = build_where_clause(ItemFilter(blocked=False))
    assert "(blocked IS NULL OR blocked = 0)" in where


def test_item_filter_exclude_blocked():
    where, _params = build_where_clause(ItemFilter(exclude_blocked=True))
    assert "(blocked IS NULL OR blocked = 0)" in where


def test_classify_item_state_returns_blocked_for_flag():
    assert classify_item_state("idea", frozen=False, blocked=True) == "blocked"
    assert classify_item_state(
        "implementing", frozen=False, blocked=True,
    ) == "blocked"


def test_classify_item_state_done_outranks_blocked_flag():
    assert classify_item_state("done", frozen=False, blocked=True) == "done"
    assert classify_item_state(
        "cancelled", frozen=False, blocked=True,
    ) == "cancelled"


def test_classify_item_state_frozen_outranks_blocked_flag():
    """Frozen ordering wins over blocked when both flags are set."""
    assert classify_item_state(
        "implementing", frozen=True, blocked=True,
    ) == "frozen"


def test_classify_item_state_legacy_blocked_status_classifies_as_active_work():
    """Legacy drift: a row whose status='blocked' (no flag) classifies as
    active_work. The dedicated ``HC-blocked-status-drift`` doctor check owns
    drift detection; the live classifier preserves pre-cutover semantics so
    the scheduler keeps offering work until the migration repairs the row."""
    assert classify_item_state("blocked", frozen=False, blocked=False) == "active_work"


def test_classify_item_state_default_blocked_is_none():
    """Default arg is None — same as un-set. No regression to existing
    callers that did not pass blocked=."""
    assert classify_item_state("idea", frozen=False) == "pipeline"
    assert classify_item_state("implementing", frozen=False) == "active_work"


def test_is_blocked_does_not_collide_with_is_frozen():
    """Independent coercion paths."""
    assert is_blocked(1) is True
    assert is_frozen(1) is True
    assert is_blocked(None) is False
    assert is_frozen(None) is False
