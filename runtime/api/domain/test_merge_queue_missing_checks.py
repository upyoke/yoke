"""Missing required checks stop an armed landing without disarming it."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_core.domain.merge_github_check_runs import LandingCheck, _parse_landing_state
from yoke_core.domain.merge_github_membership import PrQueueMembership
from yoke_core.domain.merge_landing_state import PrLandingState
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_missing_checks import (
    QUEUED_RUN_WAIT_SECONDS,
    ActiveWorkflowRun,
    missing_checks_recovery,
    missing_checks_stalled,
    read_active_workflow_run,
    read_missing_check_names,
)
from yoke_core.domain.merge_queue_readiness import classify_readiness
from yoke_core.domain.merge_queue_landing_refresh import LANDING_RECORD_STALE_SECONDS


FIXED_NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_detection_clock(monkeypatch):
    # Collection may precede execution by minutes on a full CI shard.
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_missing_checks.utc_now", lambda: FIXED_NOW
    )


def stalled_state(**changes):
    return replace(
        PrLandingState(
            merged=False,
            closed=False,
            auto_merge_active=True,
            merge_state_status="blocked",
            head_sha="cd" * 20,
            auto_merge_enabled_at=FIXED_NOW
            - timedelta(seconds=LANDING_RECORD_STALE_SECONDS + 60),
        ),
        **changes,
    )


def test_clock_is_parsed_from_github():
    state = _parse_landing_state(
        {"autoMergeRequest": {"enabledAt": "2026-11-09T12:00:00Z"}}
    )
    assert state.auto_merge_enabled_at.year == 2026


def test_stalled_readback_and_readiness_are_not_admitted():
    state = stalled_state()
    readback = LandingReadback(
        state=state,
        membership=PrQueueMembership(in_queue=False),
        required_checks=(),
        missing_checks=("signature-check",),
    )
    assert not readback.admitted()
    assert "missing-required-checks=signature-check" in readback.describe()
    assert "push a new commit" in readback.recovery(target="main")
    assert "startup_failure" in readback.recovery(target="main")
    readiness = classify_readiness(
        pr_number="42", target="main", state=state, required_checks=()
    )
    assert readiness.landing_state == "not_in_flight"
    assert readiness.needs_action
    assert "missing-required-checks=unknown" in readiness.describe()


@pytest.mark.parametrize(
    "changes,checks",
    [
        ({"auto_merge_enabled_at": FIXED_NOW}, ()),
        ({"auto_merge_enabled_at": None}, ()),
        ({"merge_state_status": "clean"}, ()),
        ({"merge_state_status": "unknown"}, ()),
        ({"queue_entry_state": "QUEUED"}, ()),
        ({"auto_merge_active": False}, ()),
        ({"merged": True}, ()),
        ({"closed": True}, ()),
        ({}, None),
        ({}, (LandingCheck("test", "in_progress", required=True),)),
        ({}, (LandingCheck("test", "completed", "failure", required=True),)),
    ],
)
def test_only_a_known_blocked_idle_landing_alarms(changes, checks):
    assert not missing_checks_stalled(stalled_state(**changes), checks)


@pytest.mark.parametrize(
    "rules,classic",
    [
        (
            [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [{"context": "signature-check"}]
                    },
                }
            ],
            [],
        ),
        ([], ["signature-check"]),
    ],
)
def test_missing_names_from_rulesets_or_classic(monkeypatch, rules, classic):
    import yoke_core.domain.merge_github_queue as github

    monkeypatch.setattr(
        github,
        "resolve_auth_detail",
        lambda *_: (SimpleNamespace(repo="o/r", token="test"), None),
    )
    paths = []

    def request(req, **_):
        paths.append(req.path)
        body = (
            rules
            if "/rules/" in req.path
            else {"protection": {"required_status_checks": {"contexts": classic}}}
        )
        return SimpleNamespace(body=body)

    assert read_missing_check_names(None, "release/main", (), request=request) == (
        "signature-check",
    )
    assert len(paths) == 2
    assert all("release%2Fmain" in path for path in paths)


def test_unreadable_names_do_not_suppress_alarm(monkeypatch):
    import yoke_core.domain.merge_github_queue as github

    monkeypatch.setattr(github, "resolve_auth_detail", lambda *_: (None, "denied"))
    assert read_missing_check_names(None, "main", ()) is None
    assert missing_checks_stalled(stalled_state(), ())


def test_observer_sends_one_notice_per_head_without_disarming(monkeypatch):
    from runtime.api.domain.merge_queue_observer_test_helpers import (
        observer_connection,
        observe,
        not_queued,
        message_count,
        message_body,
        ejected_message_id,
        inject,
        INJECTED_AT,
    )
    from yoke_core.domain.merge_queue_landing_record import read_landing_record
    import yoke_core.domain.merge_queue_missing_checks as missing

    monkeypatch.setattr(
        missing, "read_missing_check_names", lambda *_: ("signature-check",)
    )
    monkeypatch.setattr(missing, "read_active_workflow_run", lambda *_: None)
    conn = observer_connection()
    state = stalled_state()

    def run():
        return observe(
            conn,
            now=INJECTED_AT,
            read_state=lambda *_: (state, None),
            read_membership=not_queued,
            read_checks=lambda *_: ((), None),
            disarm=lambda *_: pytest.fail("missing checks must not disarm"),
        )

    assert run()["ejected"] == 1
    assert read_landing_record(conn, 101).state == "stalled"
    assert "signature-check" in message_body(conn, ejected_message_id(conn))
    inject(conn, ejected_message_id(conn))
    run()
    assert message_count(conn) == 1
    state = replace(state, head_sha="ef" * 20)
    run()
    assert message_count(conn) == 2


def test_admission_reuses_the_existing_check_projection_clock(monkeypatch):
    import yoke_core.domain.merge_github_check_runs as github
    from yoke_core.domain.merge_queue_missing_checks import (
        complete_missing_checks_readback,
    )

    state = stalled_state()
    calls = []

    def projection(*_):
        calls.append("projection")
        return github.PrLandingProjection(state=state, required_checks=())

    monkeypatch.setattr(github, "read_pr_landing_and_required_checks", projection)
    before = replace(state, auto_merge_enabled_at=None)
    enriched, checks, error = complete_missing_checks_readback(
        None, "42", before, github.read_required_checks
    )
    assert enriched.auto_merge_enabled_at == state.auto_merge_enabled_at
    assert checks == () and error is None
    assert calls == ["projection"]


def test_readiness_only_reads_names_after_detection(monkeypatch):
    import yoke_core.domain.merge_queue_missing_checks as missing
    import yoke_core.domain.merge_queue_readiness as readiness

    state = stalled_state()
    reads = SimpleNamespace(
        pr_landing_state=lambda *_: (state, None), required_checks=lambda *_: ((), None)
    )
    calls = []

    def names(*_):
        calls.append("names")
        return ("signature-check",)

    monkeypatch.setattr(missing, "read_missing_check_names", names)
    monkeypatch.setattr(missing, "read_active_workflow_run", lambda *_: None)
    result = readiness.read_merge_queue_readiness(
        None, pr_number="42", target="main", reads=reads
    )
    assert "missing-required-checks=signature-check" in result.describe()
    assert calls == ["names"]
    state = replace(state, auto_merge_enabled_at=FIXED_NOW)
    assert readiness.read_merge_queue_readiness(
        None, pr_number="42", target="main", reads=reads
    ).in_flight
    assert calls == ["names"]


@pytest.mark.parametrize("offset,expected", [(-1, False), (0, False), (1, True)])
def test_grace_boundary_uses_the_arming_clock(offset, expected):
    state = stalled_state(
        auto_merge_enabled_at=FIXED_NOW
        - timedelta(seconds=LANDING_RECORD_STALE_SECONDS + offset)
    )
    assert missing_checks_stalled(state, (), now=FIXED_NOW) is expected


def queued_run(age_seconds, status="queued"):
    return ActiveWorkflowRun(
        "signature", status, FIXED_NOW - timedelta(seconds=age_seconds)
    )


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_active_run_says_wait_instead_of_push(status):
    advice = missing_checks_recovery(("signature-check",), queued_run(600, status))
    assert f"{status.replace('_', ' ')} since 2026-11-09T11:50:00" in advice
    assert "wait for signature-check" in advice
    assert "do not push a new commit" in advice
    assert "did not start" not in advice


def test_run_queued_past_the_wait_falls_back_to_startup_advice():
    advice = missing_checks_recovery(
        ("signature-check",), queued_run(QUEUED_RUN_WAIT_SECONDS)
    )
    assert "did not start" in advice and "startup_failure" in advice


def test_stalled_readback_with_queued_run_reports_queued():
    readback = LandingReadback(
        state=stalled_state(),
        membership=PrQueueMembership(in_queue=False),
        required_checks=(),
        missing_checks=("signature-check",),
        active_run=queued_run(60),
    )
    assert not readback.admitted()
    assert "queued since" in readback.recovery(target="main")
    readiness = replace(
        classify_readiness(
            pr_number="42", target="main", state=stalled_state(), required_checks=()
        ),
        active_run=queued_run(60),
    )
    assert "queued since" in readiness.describe()


def test_active_run_read_by_head_picks_oldest_unfinished(monkeypatch):
    import yoke_core.domain.merge_github_queue as github

    monkeypatch.setattr(
        github,
        "resolve_auth_detail",
        lambda *_: (SimpleNamespace(repo="o/r", token="test"), None),
    )
    seen = []

    def request(req, **_):
        seen.append((req.path, dict(req.query)))
        runs = [
            {"name": "ci", "status": "completed", "created_at": "2026-11-09T10:00:00Z"},
            {"name": "late", "status": "queued", "created_at": "2026-11-09T11:30:00Z"},
            {"name": "sig", "status": "queued", "created_at": "2026-11-09T11:00:00Z"},
            {"name": "bad", "status": "queued", "created_at": "never"},
        ]
        return SimpleNamespace(body={"workflow_runs": runs})

    run = read_active_workflow_run(None, "cd" * 20, request=request)
    assert (run.name, run.status) == ("sig", "queued")
    assert run.since == datetime(2026, 11, 9, 11, tzinfo=timezone.utc)
    assert seen == [("/repos/o/r/actions/runs", {"head_sha": "cd" * 20, "per_page": "100"})]


def test_unreadable_runs_keep_the_startup_advice(monkeypatch):
    import yoke_core.domain.merge_github_queue as github
    from yoke_core.domain.gh_rest_transport import RestTransportError

    monkeypatch.setattr(
        github,
        "resolve_auth_detail",
        lambda *_: (SimpleNamespace(repo="o/r", token="test"), None),
    )

    def request(*_, **__):
        raise RestTransportError("outage")

    assert read_active_workflow_run(None, "cd" * 20, request=request) is None
    monkeypatch.setattr(github, "resolve_auth_detail", lambda *_: (None, "denied"))
    assert read_active_workflow_run(None, "cd" * 20) is None
