"""Tests for the shared QA vocabulary and formatting helpers."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import qa_constants
from yoke_core.domain.qa_constants import (
    BROWSER_METHOD_IDS,
    VALID_BLOCKING_MODES,
    VALID_QA_PHASES,
    VALID_REQUIREMENT_SOURCES,
    VALID_VERDICTS,
    _REQ_SELECT,
    browser_requirement_predicate,
    _coalesce,
    is_browser_method_requirement,
    _pipe_row,
)


# ---------------------------------------------------------------------------
# VALID_* tuples
# ---------------------------------------------------------------------------


def test_valid_qa_phases_tuple():
    assert isinstance(VALID_QA_PHASES, tuple)
    assert VALID_QA_PHASES == ("verification", "post_deploy", "manual_acceptance")


def test_valid_blocking_modes_tuple():
    assert isinstance(VALID_BLOCKING_MODES, tuple)
    assert VALID_BLOCKING_MODES == ("blocking", "non_blocking")


def test_valid_requirement_sources_tuple():
    assert isinstance(VALID_REQUIREMENT_SOURCES, tuple)
    assert VALID_REQUIREMENT_SOURCES == (
        "explicit",
        "seeded_default",
        "ac_derived",
        "flow_derived",
    )


def test_valid_verdicts_tuple():
    assert isinstance(VALID_VERDICTS, tuple)
    assert VALID_VERDICTS == ("pass", "fail", "undetermined", "error")


def test_browser_method_ids_tuple():
    assert isinstance(BROWSER_METHOD_IDS, tuple)
    assert BROWSER_METHOD_IDS == ("browser-check", "browser-inspection")


def test_all_valid_tuples_are_nonempty():
    """Every exported VALID_* tuple is non-empty (regression guard)."""
    for name in (
        "VALID_QA_PHASES",
        "VALID_BLOCKING_MODES",
        "VALID_REQUIREMENT_SOURCES",
        "VALID_VERDICTS",
    ):
        value = getattr(qa_constants, name)
        assert isinstance(value, tuple)
        assert len(value) > 0, f"{name} must be non-empty"


@pytest.mark.parametrize("method_id", BROWSER_METHOD_IDS)
def test_browser_method_requirement_uses_method_identity(method_id):
    assert is_browser_method_requirement(method_id)


def test_non_browser_method_is_not_browser_execution():
    assert not is_browser_method_requirement("unit-test")
    assert not is_browser_method_requirement(None)


def test_browser_requirement_predicate_uses_only_method_identity():
    predicate = browser_requirement_predicate("req")
    assert predicate == "req.method_id IN ('browser-check', 'browser-inspection')"


# ---------------------------------------------------------------------------
# _coalesce
# ---------------------------------------------------------------------------


def test_coalesce_none_returns_empty_default():
    assert _coalesce(None) == ""


def test_coalesce_none_with_explicit_default():
    assert _coalesce(None, "x") == "x"


def test_coalesce_string_passthrough():
    assert _coalesce("hello") == "hello"


def test_coalesce_int_stringified():
    assert _coalesce(42) == "42"


def test_coalesce_zero_stringified_not_default():
    """0 is not None — it must stringify, not fall through to default."""
    assert _coalesce(0) == "0"
    assert _coalesce(0, "default") == "0"


def test_coalesce_empty_string_passthrough():
    """Empty string is not None — it round-trips."""
    assert _coalesce("") == ""


# ---------------------------------------------------------------------------
# _pipe_row on an authority row object
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_row():
    # Pure row-protocol probe, NOT a Yoke-authority model: a bare ``SELECT``
    # (no Yoke table) hands ``_pipe_row`` a real authority row object to
    # verify its positional/named row-access protocol.
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        row = conn.execute("SELECT 1 AS a, 'two' AS b, NULL AS c").fetchone()
        yield row
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_pipe_row_no_cols_iterates_values_in_order(sample_row):
    assert _pipe_row(sample_row) == "1|two|"


def test_pipe_row_with_cols_picks_named_columns(sample_row):
    assert _pipe_row(sample_row, ["b", "a"]) == "two|1"


def test_pipe_row_with_cols_handles_null(sample_row):
    assert _pipe_row(sample_row, ["c", "a"]) == "|1"


def test_pipe_row_with_dict_like_row():
    """_pipe_row is documented to also work with dict-like row inputs."""
    row = {"x": 1, "y": None, "z": "hello"}
    assert _pipe_row(row, ["x", "y", "z"]) == "1||hello"


# ---------------------------------------------------------------------------
# _REQ_SELECT — canonical SELECT column list
# ---------------------------------------------------------------------------


def test_req_select_is_string_with_id_first():
    assert isinstance(_REQ_SELECT, str)
    assert _REQ_SELECT.startswith("id, ")


def test_req_select_contains_expected_columns():
    """Smoke check: every documented column appears in the SELECT list."""
    expected = (
        "id",
        "item_id",
        "epic_id",
        "task_num",
        "deployment_run_id",
        "qa_kind",
        "qa_phase",
        "target_env",
        "blocking_mode",
        "requirement_source",
        "success_policy",
        "capability_requirements",
        "suite_id",
        "waived_at",
        "waiver_rationale",
        "waiver_source",
        "created_at",
    )
    for column in expected:
        assert column in _REQ_SELECT, f"_REQ_SELECT missing {column}"
