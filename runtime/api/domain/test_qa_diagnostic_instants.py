"""QA clock diagnostics and new receipts retain exact instants and report bytes."""

import json
from datetime import timedelta

import pytest

from runtime.api.domain.test_qa_simulation_triage import _seed, _record
from yoke_contracts.timestamps import InvalidInstant, parse_instant, format_instant
from yoke_core.domain import qa_browser_freshness_check as browser
from yoke_core.domain import qa_terminal_settlement as terminal
from yoke_core.domain.events_acting_identity import acting_event_identity
from yoke_core.domain.qa_gate_definitions import LatestCodeRef
from yoke_core.domain.qa_simulation_triage import current_simulation_triage

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CLOCKS = (INSTANT, "2026-10-09T20:45:00.123456+05:45")


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_browser_stale_diagnostic_formats_only_its_clock(monkeypatch, clock):
    monkeypatch.setattr(
        browser, "query_rows", lambda *args: [{"id": 1, "method_id": "browser"}]
    )
    monkeypatch.setattr(browser, "_item_project_id", lambda *args: None)
    monkeypatch.setattr(browser, "unretracted_requirement_sql", lambda *args: "TRUE")
    monkeypatch.setattr(
        browser,
        "_latest_browser_run",
        lambda *args: {
            "created_at": clock,
            "raw_result": '{"code_identity":{"sha":"opaque sha"}}',
        },
    )
    rows = browser._collect_stale_browser_requirements(
        None, where="r.id=1", params=(), latest_code=LatestCodeRef(sha="other")
    )
    assert rows == [(1, "browser", None if clock is None else WIRE, "opaque sha", "")]


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_terminal_completion_requires_optional_native_instant(clock):
    row = {
        "id": 1,
        "run_id": 2,
        "verdict": "pass",
        "completed_at": clock,
        "requires_code_identity": False,
        "method_id": "browser",
    }
    result = terminal._issue_for_requirement(row, accepted_shas=())
    if clock is None:
        assert result.state == "incomplete"
    else:
        assert result is None
    assert row["completed_at"] == clock


@pytest.mark.parametrize(
    "clock",
    ("", "2026-10-09", "2026-10-09T15:00:00-00:00", INSTANT.replace(tzinfo=None)),
)
def test_ambiguous_diagnostic_and_completion_clocks_refuse(monkeypatch, clock):
    monkeypatch.setattr(
        browser, "query_rows", lambda *args: [{"id": 1, "method_id": "browser"}]
    )
    monkeypatch.setattr(browser, "_item_project_id", lambda *args: None)
    monkeypatch.setattr(browser, "unretracted_requirement_sql", lambda *args: "TRUE")
    monkeypatch.setattr(
        browser,
        "_latest_browser_run",
        lambda *args: {"created_at": clock, "raw_result": "{}"},
    )
    with pytest.raises(InvalidInstant):
        browser._collect_stale_browser_requirements(
            None, where="r.id=1", params=(), latest_code=LatestCodeRef()
        )
    with pytest.raises(InvalidInstant):
        terminal._issue_for_requirement(
            {"id": 1, "run_id": 2, "verdict": "pass", "completed_at": clock},
            accepted_shas=(),
        )


def test_actual_new_triage_receipt_formats_microseconds_and_preserves_capture(test_db):
    item_id, requirement_id, attempt, ref, actor = _seed(test_db)
    complete = INSTANT + timedelta(microseconds=1)
    test_db.execute(
        "UPDATE qa_runs SET started_at=%s,completed_at=%s WHERE id=%s",
        (INSTANT, complete, attempt["id"]),
    )
    test_db.commit()
    before = tuple(
        test_db.execute(
            "SELECT started_at,completed_at,raw_result FROM qa_runs WHERE id=%s",
            (attempt["id"],),
        ).fetchone()
    )
    with acting_event_identity(session_id="simulation-owner", actor_id=actor):
        receipt = _record(test_db, item_id, [ref])
        replay = _record(test_db, item_id, [ref])
    assert receipt == replay
    assert receipt["capture_started_at"] == WIRE
    assert receipt["capture_completed_at"] == format_instant(complete)
    assert receipt["report_raw_result"] == before[2]
    assert json.loads(receipt["report_raw_result"])["phase"] == "integration"
    assert current_simulation_triage(test_db, requirement_id) == receipt
    after = tuple(
        test_db.execute(
            "SELECT started_at,completed_at,raw_result FROM qa_runs WHERE id=%s",
            (attempt["id"],),
        ).fetchone()
    )
    assert after == before
