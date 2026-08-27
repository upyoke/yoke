"""The wizard reads a clone source with the GitHub access it just established."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.config import github_local_user_access
from yoke_cli.config import onboard_wizard_clone_git_copy as clone_git_copy
from yoke_cli.config import onboard_wizard_flow_clone_source as clone_source
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import project_git_probe
from yoke_cli.config import project_git_transport

URL = "https://github.com/beebauman/buzz.git"
EXTERNAL_URL = "https://gitlab.com/acme/widgets.git"


def _shell(**fields):
    return SimpleNamespace(result=SimpleNamespace(**fields))


def _probes(monkeypatch, *, anonymous, authenticated=None):
    """Record every probe as ``(url, token)`` and answer per credential."""

    seen: list[tuple[str, str | None]] = []

    def probe(url, token=None, *, github_web_url=None):
        seen.append((url, token))
        return authenticated if token else anonymous

    monkeypatch.setattr(project_git_transport, "remote_probe", probe)
    return seen


def _reachable(branch="main"):
    return project_git_probe.GitRemoteProbe(True, default_branch=branch)


def _denied():
    return project_git_probe.GitRemoteProbe(
        False, failure_kind=project_git_probe.FAILURE_ACCESS,
    )


def _unreachable():
    return project_git_probe.GitRemoteProbe(
        False, failure_kind=project_git_probe.FAILURE_NETWORK,
    )


@pytest.fixture(autouse=True)
def _default_web_url(monkeypatch):
    monkeypatch.setattr(
        github_state, "clone_web_url", lambda _result: "https://github.com",
    )


def test_private_source_is_read_with_the_connected_credential(monkeypatch) -> None:
    # The observed defect: a repo the wizard's own GitHub step can see was
    # rejected because the check only ever ran anonymously.
    monkeypatch.setattr(
        github_state, "user_access_token", lambda _result: "ghu_connected",
    )
    seen = _probes(monkeypatch, anonymous=_denied(), authenticated=_reachable())

    check = clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    assert check == clone_source.CloneRemoteCheck("main", True)
    # The connected credential reads it first — no anonymous probe of a repo
    # that credential can already see.
    assert seen == [(URL, "ghu_connected")]


def test_source_without_a_connected_credential_is_read_anonymously(
    monkeypatch,
) -> None:
    monkeypatch.setattr(github_state, "user_access_token", lambda _result: None)
    seen = _probes(monkeypatch, anonymous=_reachable("trunk"))

    check = clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    assert check == clone_source.CloneRemoteCheck("trunk", False)
    assert seen == [(URL, None)]


def test_public_source_still_resolves_when_the_credential_cannot_read_it(
    monkeypatch,
) -> None:
    # An App with narrow repository access must not make a public repo
    # unreachable: the anonymous read is the fallback, not the first move.
    monkeypatch.setattr(
        github_state, "user_access_token", lambda _result: "ghu_narrow",
    )
    seen = _probes(monkeypatch, anonymous=_reachable(), authenticated=_denied())

    check = clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    assert check == clone_source.CloneRemoteCheck("main", False)
    assert seen == [(URL, "ghu_narrow"), (URL, None)]


def test_external_source_is_never_offered_the_github_credential(
    monkeypatch,
) -> None:
    resolved: list[str] = []
    monkeypatch.setattr(
        github_state,
        "user_access_token",
        lambda _result: resolved.append("resolved") or "ghu_connected",
    )
    seen = _probes(monkeypatch, anonymous=_unreachable())

    with pytest.raises(RuntimeError) as caught:
        clone_source.CloneSourceFlow._probe_clone_remote(_shell(), EXTERNAL_URL)

    assert resolved == []
    assert seen == [(EXTERNAL_URL, None)]
    assert "never sent outside the configured GitHub origin" in str(caught.value)


def test_repo_the_credential_cannot_reach_names_app_repository_access(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        github_state, "user_access_token", lambda _result: "ghu_narrow",
    )
    _probes(monkeypatch, anonymous=_denied(), authenticated=_denied())

    with pytest.raises(RuntimeError) as caught:
        clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    assert "GitHub App has access to that repository" in str(caught.value)


def test_unconnected_run_denied_access_names_the_connection_step(
    monkeypatch,
) -> None:
    monkeypatch.setattr(github_state, "user_access_token", lambda _result: None)
    _probes(monkeypatch, anonymous=_denied())

    with pytest.raises(RuntimeError) as caught:
        clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    assert "Connect GitHub in the earlier step" in str(caught.value)


def test_credential_refresh_failure_is_named_when_the_repo_stays_unreadable(
    monkeypatch,
) -> None:
    def _raise(_result):
        raise github_local_user_access.GitHubLocalUserAccessError(
            "authorization expired.",
        )

    monkeypatch.setattr(github_state, "user_access_token", _raise)
    seen = _probes(monkeypatch, anonymous=_denied())

    with pytest.raises(RuntimeError) as caught:
        clone_source.CloneSourceFlow._probe_clone_remote(_shell(), URL)

    # The anonymous read still runs, so a public source survives a stale
    # credential; only an unreadable one surfaces the refresh failure.
    assert seen == [(URL, None)]
    assert "authorization expired." in str(caught.value)
    assert "Reconnect GitHub" in str(caught.value)


def test_every_unreachable_reason_names_a_recovery_step() -> None:
    reasons = [
        clone_git_copy.unreachable_source_reason(
            configured_origin=configured,
            used_connected_github=used,
            credential_error=error,
            denied_access=denied,
        )
        for configured, used, error, denied in (
            (True, False, "expired.", False),
            (True, True, None, True),
            (False, False, None, False),
            (True, False, None, True),
            (True, False, None, False),
        )
    ]

    assert len(set(reasons)) == len(reasons)
    assert all(reason.startswith("Yoke couldn't") for reason in reasons)
