"""Daemon startup for a relay whose machine serves its own control plane."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_relay_release as release_cli
from yoke_cli.config import session_relay_instance
from yoke_core.tools import session_relay_release
from yoke_core.tools import session_relay_release_install
from yoke_harness import session_relay_daemon


def test_local_universe_daemon_serves_without_following_a_release(
    monkeypatch,
    tmp_path,
) -> None:
    """A local relay already runs the build its own machine serves.

    Passing no ``pin_served_release`` is what turns release-following off in
    the daemon loop, so the relay never reaches for a served build, a
    distribution index, or a restart into a pinned interpreter.
    """
    instance = SimpleNamespace(
        environment="local",
        state_dir=tmp_path / "relay",
        follows_served_release=False,
    )
    daemon_call = {}

    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )

    def unreachable_status(**_kwargs):
        raise AssertionError("a local relay must not read a served release")

    def unreachable_pin(**_kwargs):
        raise AssertionError("a local relay must not pin a release")

    monkeypatch.setattr(
        session_relay_release, "relay_release_status", unreachable_status
    )
    monkeypatch.setattr(
        session_relay_release_install, "pin_relay_release", unreachable_pin
    )

    def serve_forever(**kwargs):
        daemon_call.update(kwargs)
        return SimpleNamespace(reason="stopped")

    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)

    outcome = release_cli.serve_release_daemon(cycle_maintenance=lambda: None)

    assert outcome.reason == "stopped"
    assert daemon_call["state_dir"] == instance.state_dir
    assert daemon_call.get("pin_served_release") is None
    assert "pinned_release" not in daemon_call
    assert "reload_argv" not in daemon_call


def test_local_universe_daemon_hosts_github_observation(monkeypatch, tmp_path) -> None:
    """With no API server, the standing local relay hosts the GitHub observers."""
    from contextlib import contextmanager

    from yoke_core.domain import pending_github_observation_job as observation

    instance = SimpleNamespace(
        environment="local",
        state_dir=tmp_path / "relay",
        follows_served_release=False,
    )
    hosting: list[bool] = []

    @contextmanager
    def job():
        hosting.append(True)
        yield
        hosting.append(False)

    def serve_forever(**_kwargs):
        assert hosting == [True]
        return SimpleNamespace(reason="stopped")

    monkeypatch.setattr(
        session_relay_instance, "resolve_relay_instance", lambda: instance
    )
    monkeypatch.setattr(observation, "pending_github_observation_job", job)
    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)

    outcome = release_cli.serve_release_daemon(cycle_maintenance=lambda: None)

    assert outcome.reason == "stopped"
    assert hosting == [True, False]
