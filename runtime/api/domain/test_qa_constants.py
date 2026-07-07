"""Tests for ``yoke_core.domain.qa_constants`` leaf module.

Covers AC-10 from the parent task spec:

- (a) every ``VALID_*`` tuple is the expected non-empty tuple.
- (b) ``_normalize_qa_phase`` normalizes ``"validation"`` to
  ``"verification"`` and is a no-op on canonical values.
- (c) ``_normalize_qa_kind`` round-trips canonical browser QA kinds and
  rewrites the legacy ``"review"`` value to ``"implementation_review"``.
- (d) ``_coalesce(None)`` returns the default; ``_coalesce(value)`` returns
  ``str(value)``.
- (e) ``_pipe_row`` matches the current behavior on a representative
  authority row object.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import qa_constants
from yoke_core.domain.qa_constants import (
    VALID_BLOCKING_MODES,
    VALID_BROWSER_QA_KINDS,
    VALID_QA_PHASES,
    VALID_REQUIREMENT_SOURCES,
    VALID_VERDICTS,
    _REQ_SELECT,
    _coalesce,
    _normalize_qa_kind,
    _normalize_qa_phase,
    _pipe_row,
)


# ---------------------------------------------------------------------------
# AC-10 (a): VALID_* tuples
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
    assert VALID_VERDICTS == ("pass", "fail", "inconclusive", "error")


def test_valid_browser_qa_kinds_tuple():
    assert isinstance(VALID_BROWSER_QA_KINDS, tuple)
    assert VALID_BROWSER_QA_KINDS == ("browser_smoke", "browser_diff")


def test_all_valid_tuples_are_nonempty():
    """Every exported VALID_* tuple is non-empty (regression guard)."""
    for name in (
        "VALID_QA_PHASES",
        "VALID_BLOCKING_MODES",
        "VALID_REQUIREMENT_SOURCES",
        "VALID_VERDICTS",
        "VALID_BROWSER_QA_KINDS",
    ):
        value = getattr(qa_constants, name)
        assert isinstance(value, tuple)
        assert len(value) > 0, f"{name} must be non-empty"


# ---------------------------------------------------------------------------
# AC-10 (b): _normalize_qa_phase
# ---------------------------------------------------------------------------

def test_normalize_qa_phase_canonical_passes_through():
    assert _normalize_qa_phase("verification") == "verification"
    assert _normalize_qa_phase("post_deploy") == "post_deploy"
    assert _normalize_qa_phase("manual_acceptance") == "manual_acceptance"


def test_normalize_qa_phase_legacy_validation_to_verification():
    assert _normalize_qa_phase("validation") == "verification"


def test_normalize_qa_phase_unknown_passes_through():
    """Unknown values are returned unchanged (validation happens elsewhere)."""
    assert _normalize_qa_phase("custom_phase") == "custom_phase"


def test_normalize_qa_phase_is_case_sensitive():
    """The current implementation does not lower-case its input."""
    assert _normalize_qa_phase("VERIFICATION") == "VERIFICATION"


# ---------------------------------------------------------------------------
# AC-10 (c): _normalize_qa_kind
# ---------------------------------------------------------------------------

def test_normalize_qa_kind_browser_smoke_round_trips():
    assert _normalize_qa_kind("browser_smoke") == "browser_smoke"


def test_normalize_qa_kind_browser_diff_round_trips():
    assert _normalize_qa_kind("browser_diff") == "browser_diff"


def test_normalize_qa_kind_legacy_review_rewritten():
    assert _normalize_qa_kind("review") == "implementation_review"


def test_normalize_qa_kind_unknown_passes_through():
    assert _normalize_qa_kind("custom_kind") == "custom_kind"


# ---------------------------------------------------------------------------
# AC-10 (d): _coalesce
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
# AC-10 (e): _pipe_row on an authority row object
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
