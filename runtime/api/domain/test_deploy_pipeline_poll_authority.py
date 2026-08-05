"""Naming the GitHub status authority, and escalating instead of repeating.

The failure this covers is not a crash. It is a deploy that emits the same
sentence once per retry while an operator cannot tell what it is waiting on,
which is how one real outage produced 37 indistinguishable lines.
"""

from __future__ import annotations

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import deploy_pipeline_poll_authority as poll_authority


def _clear(monkeypatch) -> None:
    monkeypatch.delenv(poll_authority.GITHUB_ACTIONS_RELAY_ENV, raising=False)
    monkeypatch.delenv(
        poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, raising=False
    )
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)


def test_an_explicit_relay_env_is_named(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(poll_authority.GITHUB_ACTIONS_RELAY_ENV, "prod")
    assert "'prod'" in poll_authority.authority_label()
    assert "relay" in poll_authority.authority_label()


def test_the_relay_derived_from_an_admin_env_is_named(monkeypatch):
    """The pipeline's normal shape: an operator selects the db-admin env and
    the relay is derived from its sibling, so the label has to follow."""
    _clear(monkeypatch)
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    assert "'prod'" in poll_authority.authority_label()


def test_local_app_authority_is_named_as_attended(monkeypatch):
    """It is a different failure mode than a relay and must read differently."""
    _clear(monkeypatch)
    monkeypatch.setenv(
        poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "1"
    )
    label = poll_authority.authority_label()
    assert "local GitHub App authority" in label
    assert "attended" in label


def test_local_authority_wins_over_a_stale_admin_env(monkeypatch):
    """Selecting the local App authority is explicit; a lingering admin env
    must not silently relabel it as a relay."""
    _clear(monkeypatch)
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    monkeypatch.setenv(
        poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "1"
    )
    assert "local GitHub App authority" in poll_authority.authority_label()


def test_an_unresolvable_authority_still_names_something(monkeypatch):
    """Never render an empty authority — the label exists to be read."""
    _clear(monkeypatch)
    label = poll_authority.authority_label()
    assert label
    assert "control plane" in label


def test_early_failures_report_every_time():
    """The first retries are ordinary and stay verbatim."""
    for n in range(1, poll_authority.ESCALATE_AFTER):
        assert poll_authority.should_report(n)


def test_the_escalation_point_reports():
    assert poll_authority.should_report(poll_authority.ESCALATE_AFTER)


def test_between_restatements_nothing_is_printed():
    """The whole point: stop emitting one line per retry."""
    quiet = [
        n
        for n in range(poll_authority.ESCALATE_AFTER + 1, 200)
        if not poll_authority.should_report(n)
    ]
    assert quiet, "escalation must suppress something or it changed nothing"
    # The observed outage printed 37 consecutive lines; the same run now
    # prints a small handful.
    reported = [n for n in range(1, 38) if poll_authority.should_report(n)]
    assert len(reported) < 10


def test_it_restates_periodically_so_a_long_wait_still_shows_progress():
    assert poll_authority.should_report(poll_authority.RESTATE_EVERY * 2)


def test_the_stall_message_names_the_dependency_and_the_way_out():
    """An operator reading this should not have to ask anything else."""
    message = poll_authority.stall_message("30968749771", 12)
    assert "12 consecutive" in message
    # The dependency that makes the failure self-sustaining.
    assert "control plane" in message
    assert "cannot observe itself" in message
    # The independent surface that answers while the relay cannot.
    assert "gh run view 30968749771" in message
    # And that the deploy has not given up.
    assert "stage budget" in message
