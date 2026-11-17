"""Protection reads decide whether an armed BLOCKED landing really stalled."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.test_merge_queue_missing_checks import stalled_state
from yoke_core.domain.merge_github_check_runs import LandingCheck
from yoke_core.domain.merge_github_membership import PrQueueMembership
from yoke_core.domain.merge_queue_enqueue_verification import (
    LandingReadback,
    admission_facts_for_state,
)
from yoke_core.domain.merge_queue_missing_checks import read_missing_check_names
from yoke_core.domain.merge_queue_readiness import read_merge_queue_readiness


@pytest.mark.parametrize("error", [None, "rules endpoint denied"])
def test_blocked_passed_head_admission_and_readiness(monkeypatch, error):
    import yoke_core.domain.merge_queue_missing_checks as missing

    state = stalled_state()
    checks = (LandingCheck("ci", "completed", "success", required=True),)
    monkeypatch.setattr(
        missing,
        "read_missing_check_names",
        lambda *_: (None, error) if error else ((), None),
    )
    monkeypatch.setattr(
        missing,
        "read_active_workflow_run",
        lambda *_: pytest.fail("No missing check was named"),
    )
    readback = admission_facts_for_state(
        SimpleNamespace(args=SimpleNamespace(target="main")),
        "42",
        state,
        read_membership=lambda *_: (PrQueueMembership(in_queue=False), None),
        read_checks=lambda *_: (checks, None),
    )
    assert readback.admitted() is (not error)
    assert "push" not in readback.recovery(target="main")
    result = read_merge_queue_readiness(
        None,
        pr_number="42",
        target="main",
        reads=SimpleNamespace(
            pr_landing_state=lambda *_: (state, None),
            required_checks=lambda *_: (checks, None),
        ),
    )
    if error:
        assert "required_checks_unreadable: rules endpoint denied" in result.describe()
        assert not result.in_flight
    else:
        assert result.in_flight
        assert "missing-required-checks" not in result.describe()
    assert "push" not in result.describe()


def test_passed_blocked_head_does_not_send_stopped_notice(monkeypatch):
    import yoke_core.domain.merge_queue_missing_checks as missing
    from runtime.api.domain.merge_queue_observer_test_helpers import (
        INJECTED_AT,
        message_count,
        not_queued,
        observe,
        observer_connection,
    )

    monkeypatch.setattr(missing, "read_missing_check_names", lambda *_: ((), None))
    state = stalled_state()
    conn = observer_connection()
    result = observe(
        conn,
        now=INJECTED_AT,
        read_state=lambda *_: (state, None),
        read_membership=not_queued,
        read_checks=lambda *_: (
            (LandingCheck("ci", "completed", "success", required=True),),
            None,
        ),
        disarm=lambda *_: pytest.fail("Passed checks must remain armed"),
    )
    assert result["ejected"] == 0
    assert message_count(conn) == 0


def test_partial_protection_read_reports_the_error(monkeypatch):
    import yoke_core.domain.merge_github_queue as github
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.merge_queue_missing_checks import read_missing_check_names

    monkeypatch.setattr(
        github,
        "resolve_auth_detail",
        lambda *_: (SimpleNamespace(repo="o/r", token="test"), None),
    )

    def request(req, **_):
        if "/rules/" in req.path:
            raise RestTransportError("rules denied")
        return SimpleNamespace(
            body={"protection": {"required_status_checks": {"contexts": ["ci"]}}}
        )

    names, error = read_missing_check_names(None, "main", (), request=request)
    assert names is None and "rules denied" in error


def test_unreadable_names_report_access_recovery(monkeypatch):
    import yoke_core.domain.merge_github_queue as github

    monkeypatch.setattr(github, "resolve_auth_detail", lambda *_: (None, "denied"))
    names, error = read_missing_check_names(None, "main", ())
    assert names is None and error == "denied"
    readback = LandingReadback(
        state=stalled_state(),
        membership=PrQueueMembership(in_queue=False),
        required_checks=(),
        missing_checks_error=error,
    )
    assert not readback.admitted()
    advice = readback.recovery(target="main")
    assert "required_checks_unreadable: denied" in advice
    assert "restore protection/ruleset read access, then re-run observation" in advice
    assert "push" not in advice
