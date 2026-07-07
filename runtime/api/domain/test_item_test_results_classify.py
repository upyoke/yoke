"""Tests for the shared ``items.test_results`` classifier + reader.

Covers ``classify_test_results`` branches (empty / failed / passed) and
the ``read_item_test_results`` fixture-DB roundtrip the polish gate and
merge engine both depend on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.item_test_results_classify import (
    classify_test_results,
    read_item_test_results,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


_PYTEST_PASS_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ............                                          [100%]\n\n"
    "============================== 12 passed in 1.42s =============================="
)
_PYTEST_FAILED_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ...F........                                          [100%]\n\n"
    "FAILED tests/test_foo.py::test_bar - AssertionError\n"
    "=========================== 1 failed, 11 passed ============================="
)
_PYTEST_ERROR_OUTPUT = (
    "tests/test_foo.py::test_bar ERROR\n"
    "=========================== 1 errors in 0.5s ==========================="
)
_PYTEST_Q_PASS_OUTPUT = (
    "....................................................................\n"
    "....................................................................\n"
    "\n"
    "454 passed in 2.13s"
)
_PYTEST_Q_FAILED_OUTPUT = (
    ".F.....\n"
    "FAILED tests/test_foo.py::test_bar - AssertionError\n"
    "1 failed, 11 passed in 1.23s"
)


class TestClassify:
    def test_empty_string_is_empty(self) -> None:
        assert classify_test_results("") == "empty"

    def test_whitespace_only_is_empty(self) -> None:
        assert classify_test_results("   \n  \t") == "empty"

    def test_pass_verdict(self) -> None:
        assert classify_test_results(_PYTEST_PASS_OUTPUT) == "passed"

    def test_failed_signature(self) -> None:
        assert classify_test_results(_PYTEST_FAILED_OUTPUT) == "failed"

    def test_error_signature(self) -> None:
        assert classify_test_results(_PYTEST_ERROR_OUTPUT) == "failed"

    def test_unrecognized_prose_falls_through_to_empty(self) -> None:
        assert classify_test_results("running tests...") == "empty"

    def test_failure_token_wins_over_pass_count(self) -> None:
        mixed = (
            "FAILED tests/test_foo.py::test_bar\n"
            "==== 1 failed, 11 passed in 1.23s ===="
        )
        assert classify_test_results(mixed) == "failed"

    def test_q_mode_standalone_verdict(self) -> None:
        """`pytest -q` emits the verdict line without the equals banner."""
        assert classify_test_results("454 passed in 2.13s") == "passed"

    def test_q_mode_with_dot_progress(self) -> None:
        """The full quiet-mode shape: dots then a final standalone verdict."""
        assert classify_test_results(_PYTEST_Q_PASS_OUTPUT) == "passed"

    def test_q_mode_failure_signature_wins(self) -> None:
        """Failure tokens still beat the pass count in quiet-mode output."""
        assert classify_test_results(_PYTEST_Q_FAILED_OUTPUT) == "failed"

    def test_q_mode_verdict_without_timing(self) -> None:
        """`N passed` alone (no `in TIMEs`) is still a valid quiet verdict."""
        assert classify_test_results("12 passed") == "passed"

    def test_prose_pass_without_count_is_empty(self) -> None:
        """`all tests passed` and similar prose lacks a numeric verdict line."""
        assert classify_test_results("all tests passed") == "empty"
        assert classify_test_results("everything passed cleanly") == "empty"

    def test_sun_1836_field_note_capture_classifies_as_passed(self) -> None:
        """Replay of field-note 07bde8a3 — YOK-1836's quiet-mode capture."""
        blob = (
            "....................................................................\n"
            "....................................................................\n"
            "\n"
            "454 passed in 2.13s"
        )
        assert classify_test_results(blob) == "passed"


@pytest.fixture
def fixture_db(tmp_path: Path):
    # Backend-aware: a SQLite file on SQLite, a disposable per-test database on
    # Postgres (YOKE_PG_DSN repointed for the context's lifetime). The same
    # repointed DSN backs both the seed connection here and the standalone
    # connection ``read_item_test_results(db_path=...)`` opens, so insert and
    # read hit one store. ``db_path`` is the real file on SQLite and the ignored
    # placeholder on Postgres (the connection target is the DSN).
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn, db_path
        finally:
            conn.close()


class TestReader:
    def test_round_trip_returns_stored_test_results(self, fixture_db) -> None:
        conn, db_path = fixture_db
        insert_item(
            conn, id=7001, project="yoke", status="polishing-implementation",
            test_results=_PYTEST_PASS_OUTPUT,
        )
        assert read_item_test_results(7001, db_path=db_path) == _PYTEST_PASS_OUTPUT

    def test_missing_row_returns_empty(self, fixture_db) -> None:
        _conn, db_path = fixture_db
        assert read_item_test_results(9999, db_path=db_path) == ""

    def test_null_column_returns_empty(self, fixture_db) -> None:
        conn, db_path = fixture_db
        insert_item(
            conn, id=7002, project="yoke", status="polishing-implementation",
            test_results=None,
        )
        assert read_item_test_results(7002, db_path=db_path) == ""

    def test_accepts_yok_n_prefix(self, fixture_db) -> None:
        conn, db_path = fixture_db
        insert_item(
            conn, id=7003, project="yoke", status="polishing-implementation",
            test_results=_PYTEST_PASS_OUTPUT,
        )
        assert read_item_test_results("YOK-7003", db_path=db_path) == _PYTEST_PASS_OUTPUT
        assert read_item_test_results("YOK-07003", db_path=db_path) == _PYTEST_PASS_OUTPUT

    def test_unparseable_id_returns_empty(self, fixture_db) -> None:
        _conn, db_path = fixture_db
        assert read_item_test_results("not-a-number", db_path=db_path) == ""
        assert read_item_test_results("", db_path=db_path) == ""
        assert read_item_test_results(0, db_path=db_path) == ""
        assert read_item_test_results(-5, db_path=db_path) == ""

    def test_passes_through_classifier_pipeline(self, fixture_db) -> None:
        """The two helpers compose: read then classify."""
        conn, db_path = fixture_db
        insert_item(
            conn, id=7004, project="yoke", status="polishing-implementation",
            test_results=_PYTEST_FAILED_OUTPUT,
        )
        verdict = classify_test_results(read_item_test_results(7004, db_path=db_path))
        assert verdict == "failed"
