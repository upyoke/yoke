"""QA clock diagnostics and new receipts retain exact instants and report bytes."""

import json
from datetime import timedelta

import pytest

from runtime.api.domain.test_qa_simulation_triage import _seed, _record
from yoke_contracts.timestamps import InvalidInstant, parse_instant, format_instant
from yoke_core.domain import qa_browser_freshness_check as browser
from yoke_core.domain import qa_terminal_settlement as terminal
from yoke_core.domain import qa_gate_helpers as gate_helpers
from yoke_core.domain.events_acting_identity import acting_event_identity
from yoke_core.domain.qa_gate_definitions import GateTarget, LatestCodeRef
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


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_commit_reference_retains_native_clock_until_diagnostic(clock):
    ref = LatestCodeRef(
        branch="opaque branch",
        sha="opaque sha",
        timestamp=clock,
        accepted_shas=("opaque accepted sha",),
    )
    assert ref.timestamp == (None if clock is None else INSTANT)
    if ref.timestamp is not None:
        assert ref.timestamp.utcoffset() == timedelta(0)
    assert ref.accepted_shas == ("opaque accepted sha",)
    errors = browser._browser_freshness_errors(
        name="item",
        transition_name="review",
        latest_code=ref,
        stale_rows=[],
    )
    assert "  Branch: opaque branch" in errors
    assert "  Latest SHA: opaque sha" in errors
    assert (f"  Latest commit: {WIRE}" in errors) == (clock is not None)


@pytest.mark.parametrize("clock", CLOCKS + (None,))
def test_commit_override_parses_at_native_reference_ingress(monkeypatch, clock):
    monkeypatch.setenv("YOKE_QA_GATE_BRANCH", "opaque branch")
    monkeypatch.setenv("YOKE_QA_GATE_COMMIT_SHA", "opaque sha")
    if clock is None:
        monkeypatch.delenv("YOKE_QA_GATE_COMMIT_TS", raising=False)
    else:
        monkeypatch.setenv(
            "YOKE_QA_GATE_COMMIT_TS",
            clock if isinstance(clock, str) else format_instant(clock),
        )
    ref = gate_helpers._git_latest_code_ref(GateTarget(item_id=1), "unused")
    assert ref == LatestCodeRef(
        branch="opaque branch",
        sha="opaque sha",
        timestamp=clock,
    )


@pytest.mark.parametrize(
    "clock",
    ("", "2026-10-09", "2026-10-09T15:00:00-00:00", INSTANT.replace(tzinfo=None)),
)
def test_commit_reference_refuses_ambiguous_clock(clock):
    with pytest.raises(InvalidInstant):
        LatestCodeRef(timestamp=clock)


def test_git_commit_seconds_enter_native_reference(monkeypatch, tmp_path):
    from subprocess import CompletedProcess

    for name in (
        "YOKE_QA_GATE_BRANCH",
        "YOKE_QA_GATE_COMMIT_SHA",
        "YOKE_QA_GATE_COMMIT_TS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        gate_helpers, "_resolve_target_branch_project", lambda *args: ("branch", None)
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return CompletedProcess(command, 0, str(tmp_path))
        assert command == [
            "git",
            "-C",
            str(tmp_path),
            "log",
            "-1",
            "--format=%H|%cd",
            "--date=format:%Y-%m-%dT%H:%M:%SZ",
            "branch",
        ]
        assert kwargs["env"]["TZ"] == "UTC"
        return CompletedProcess(command, 0, "opaque sha|2026-10-09T15:00:00Z\n")

    monkeypatch.setattr(gate_helpers.subprocess, "run", run)
    ref = gate_helpers._git_latest_code_ref(GateTarget(item_id=1), "unused")
    assert ref.timestamp == INSTANT.replace(microsecond=0)
    assert ref.sha == "opaque sha"
    assert len(commands) == 2
