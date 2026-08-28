"""What a failed remote git command reports, and which recovery it names."""

from __future__ import annotations

import subprocess
import urllib.error

import pytest

from yoke_cli.config import credentialed_git as cg
from yoke_cli.config import credentialed_git_attribution as attribution
from yoke_cli.config import credentialed_git_command as cgc
from yoke_cli.config import github_git_credential_file as credential_file


WEB_URL = "https://github.com"
HTTPS_ORIGIN = "https://github.com/acme/widgets.git"
OTHER_ORIGIN = "https://gitlab.example/acme/widgets.git"
STORE = "yoke_cli.config.github_git_credential_store.access_token_from_machine_config"


def _failed(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(argv, 128, "", "fatal: Authentication failed")


def _store_failure(cause: BaseException) -> RuntimeError:
    """Build the store's wrapped refusal with the cause a classifier reads."""

    error = RuntimeError("the credential store could not answer")
    error.__cause__ = cause
    return error


def _attribution_of(args, monkeypatch, *, origin: str, token: str | None) -> str:
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: origin)
    if token is not None:
        monkeypatch.setattr(cg, "resolve_token", lambda url: token)
    monkeypatch.setattr(
        cg, "_run", lambda argv, **kwargs: _failed(argv),
    )
    return cg.run(args).stderr


def test_a_credentialed_push_reports_that_the_credential_was_applied(monkeypatch):
    stderr = _attribution_of(
        ["-C", "/repo", "push", "origin", "main"],
        monkeypatch,
        origin=HTTPS_ORIGIN,
        token="gho_stored",
    )

    assert "credential WAS applied" in stderr
    assert HTTPS_ORIGIN in stderr


def test_an_uncredentialed_push_never_claims_a_credential_was_applied(monkeypatch):
    """The defect an after-the-fact attribution cannot catch.

    Re-deriving the answer from the target alone reports the same sentence
    whether the run carried a credential or not, and those need opposite
    responses.
    """

    stderr = _attribution_of(
        ["-C", "/repo", "fetch", "origin"],
        monkeypatch,
        origin=OTHER_ORIGIN,
        token=None,
    )

    assert "No credential was applied" in stderr
    assert "WAS applied" not in stderr


def test_a_local_command_is_not_attributed_at_all(monkeypatch):
    monkeypatch.setattr(cg, "_run", lambda argv, **kwargs: _failed(argv))

    stderr = cg.run(["-C", "/repo", "status"]).stderr

    assert stderr == "fatal: Authentication failed"


def test_a_rejected_credential_advises_retrying_rather_than_reconnecting():
    """Reconnecting is the one action that turns this into a fleet outage.

    `yoke github connect --replace` rotates the authorization and revokes the
    access token every other running command holds, so no failure path may
    recommend it for what is almost always contention.
    """

    line = attribution.attribution(
        attribution.CredentialDecision(
            network=True, url=HTTPS_ORIGIN, web_url=WEB_URL, token_applied=True,
        )
    )

    assert "retry the command" in line
    assert "Do not reconnect" in line
    assert "yoke github connect" not in line


def test_a_contended_credential_read_is_retried_before_it_refuses(monkeypatch):
    attempts: list[int] = []

    def _busy_then_ready(config_path, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise _store_failure(credential_file.CredentialFileBusy("busy"))
        return {"access_token": "gho_stored"}

    monkeypatch.setattr(STORE, _busy_then_ready)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    assert cg.resolve_token(HTTPS_ORIGIN) == "gho_stored"
    assert len(attempts) == 2


def test_a_persistent_contention_failure_names_retry_not_reconnect(monkeypatch):
    def _busy(config_path, **kwargs):
        raise _store_failure(credential_file.CredentialFileBusy("busy"))

    monkeypatch.setattr(STORE, _busy)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(cg.CredentialedGitError) as excinfo:
        cg.resolve_token(HTTPS_ORIGIN)

    message = str(excinfo.value)
    assert "still stands" in message
    assert "yoke github connect" not in message


def test_an_absent_authorization_still_names_reconnect(monkeypatch):
    def _absent(config_path, **kwargs):
        raise RuntimeError("machine GitHub App authorization is not configured")

    monkeypatch.setattr(STORE, _absent)

    with pytest.raises(cg.CredentialedGitError) as excinfo:
        cg.resolve_token(HTTPS_ORIGIN)

    assert "yoke github connect" in str(excinfo.value)


def test_an_unreachable_github_is_retried_then_reported_as_transient(monkeypatch):
    calls: list[int] = []

    def _unreachable(config_path, **kwargs):
        calls.append(1)
        raise _store_failure(urllib.error.URLError("no route to host"))

    monkeypatch.setattr(STORE, _unreachable)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(cg.CredentialedGitError) as excinfo:
        cg.resolve_token(HTTPS_ORIGIN)

    assert len(calls) == 3
    assert "still stands" in str(excinfo.value)
