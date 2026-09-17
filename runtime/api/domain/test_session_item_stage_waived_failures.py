"""A settled QA case must stop painting the item stage strip red.

Waiving a requirement is how a case is dispositioned: the run that failed
stays on the record, and a replacement case answers in its place. The strip
read only the latest run per requirement, so an item that had superseded a
failing case kept showing that case's red beside the passing one that
replaced it. These pin the disposition, and pin that a live failure is
still reported.
"""

from __future__ import annotations

from typing import Any

from runtime.api.item_page_reads_test_support import _connection
from yoke_core.domain.session_item_stage_failures import qa_failures

ITEM = 51


def _requirement(
    conn: Any, requirement_id: int, *, transition: str, waived_at: str | None
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, workflow_transition_id, waived_at) "
        "VALUES (?, ?, 'method_case', 'verification', '{}', 'now', "
        "'browser-inspection', ?, ?)",
        (requirement_id, ITEM, transition, waived_at),
    )


def _run(conn: Any, run_id: int, requirement_id: int, verdict: str) -> None:
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, verdict, raw_result) "
        "VALUES (?, ?, ?, '{}')",
        (run_id, requirement_id, verdict),
    )


def test_a_waived_failure_beside_a_passing_case_paints_nothing() -> None:
    """The shape this guards: a case failed, was waived, and a replacement
    case passed. Only the live requirement speaks."""
    conn = _connection()
    _requirement(conn, 1, transition="reviewing-implementation", waived_at="now")
    _run(conn, 10, 1, "fail")
    _requirement(conn, 2, transition="reviewing-implementation", waived_at=None)
    _run(conn, 11, 2, "pass")
    conn.commit()

    assert qa_failures(conn, [ITEM]) == {}


def test_an_unwaived_failure_still_paints_its_transition() -> None:
    """The disposition is the only thing that silences a failure; a live
    requirement's latest failing run is still the signal it was."""
    conn = _connection()
    _requirement(conn, 1, transition="reviewing-implementation", waived_at=None)
    _run(conn, 10, 1, "fail")
    conn.commit()

    assert qa_failures(conn, [ITEM]) == {ITEM: "reviewing-implementation"}


def test_an_unwaived_error_is_a_failure_too() -> None:
    conn = _connection()
    _requirement(conn, 1, transition="reviewing-implementation", waived_at=None)
    _run(conn, 10, 1, "error")
    conn.commit()

    assert qa_failures(conn, [ITEM]) == {ITEM: "reviewing-implementation"}


def test_waiving_hides_the_failure_without_deleting_its_run() -> None:
    """History is preserved: the waiver changes what the strip reads, not
    what the record holds."""
    conn = _connection()
    _requirement(conn, 1, transition="reviewing-implementation", waived_at="now")
    _run(conn, 10, 1, "fail")
    conn.commit()

    assert qa_failures(conn, [ITEM]) == {}
    surviving = conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id = 1"
    ).fetchall()
    assert [row["verdict"] for row in surviving] == ["fail"]
