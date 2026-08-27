"""The credentialed git environment every engine remote operation runs under."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from yoke_cli.config import credentialed_git as cg
from yoke_cli.config import credentialed_git_command as cgc


WEB_URL = "https://github.com"
HTTPS_ORIGIN = "https://github.com/acme/widgets.git"
SSH_ORIGIN = "git@github.com:acme/widgets.git"


class _Token:
    def __init__(self, value: str, expires_in_seconds: int = 3600) -> None:
        self.access_token = value
        self.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in_seconds
        )


@pytest.fixture(autouse=True)
def _clear_token_cache():
    cg._cached_token = None
    yield
    cg._cached_token = None


@pytest.fixture
def stored_token(monkeypatch):
    """Serve one machine credential without reaching the machine profile."""
    monkeypatch.setattr(cg, "resolve_token", lambda url: "gho_stored")
    return "gho_stored"


def _config_values(env: dict[str, str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for index in range(int(env["GIT_CONFIG_COUNT"])):
        key = env[f"GIT_CONFIG_KEY_{index}"]
        values.setdefault(key, []).append(env[f"GIT_CONFIG_VALUE_{index}"])
    return values


@pytest.mark.parametrize(
    "args,expected",
    [
        (["push", "origin", "main"], "push"),
        (["-C", "/repo", "push", "origin", "main"], "push"),
        (["-c", "core.pager=cat", "-C", "/repo", "fetch"], "fetch"),
        (["--git-dir", "/repo/.git", "ls-remote"], "ls-remote"),
        (["status", "--porcelain"], "status"),
        ([], ""),
    ],
)
def test_split_git_args_finds_the_subcommand_behind_global_options(args, expected):
    assert cgc.split_git_args(args)[1] == expected


@pytest.mark.parametrize(
    "args,network",
    [
        (["push", "origin", "main"], True),
        (["-C", "/repo", "push", "origin", "main"], True),
        (["fetch", "--quiet", "origin"], True),
        (["ls-remote", "--heads", "origin"], True),
        (["pull", "--ff-only", "origin", "main"], True),
        (["clone", HTTPS_ORIGIN], True),
        (["remote", "update"], True),
        (["remote", "get-url", "origin"], False),
        (["status", "--porcelain"], False),
        (["rev-parse", "HEAD"], False),
        (["merge-base", "--is-ancestor", "a", "b"], False),
    ],
)
def test_network_commands_are_the_ones_that_contact_a_remote(args, network):
    assert cgc.is_network_command(args) is network


def test_command_cwd_prefers_the_dash_c_target():
    assert cgc.command_cwd(["-C", "/repo", "fetch"], "/elsewhere") == "/repo"
    assert cgc.command_cwd(["fetch"], "/elsewhere") == "/elsewhere"


def test_contact_url_resolves_a_named_remote_through_the_checkout(monkeypatch):
    monkeypatch.setattr(
        cgc, "remote_url", lambda repo, remote: f"{repo}:{remote}",
    )
    assert cgc.contact_url(["-C", "/repo", "fetch", "origin"], None) == "/repo:origin"
    assert cgc.contact_url(["push", "--force"], "/repo") == "/repo:origin"


def test_contact_url_takes_a_url_operand_as_written():
    assert cgc.contact_url(["ls-remote", HTTPS_ORIGIN], None) == HTTPS_ORIGIN
    assert cgc.contact_url(["clone", SSH_ORIGIN, "dest"], None) == SSH_ORIGIN


def test_local_commands_never_resolve_a_credential(monkeypatch):
    def _refuse(url):
        raise AssertionError("a local command must not resolve a credential")

    monkeypatch.setattr(cg, "resolve_token", _refuse)
    with cg.git_environment(["-C", "/repo", "status"], cwd=None) as env:
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "GIT_CONFIG_COUNT" not in env


def test_a_non_github_remote_runs_without_a_github_credential(monkeypatch):
    def _refuse(url):
        raise AssertionError("a non-GitHub remote must not carry the token")

    monkeypatch.setattr(cg, "resolve_token", _refuse)
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(
        cgc, "remote_url", lambda repo, remote: "https://gitlab.example/a/b.git",
    )
    with cg.git_environment(["-C", "/repo", "fetch", "origin"], cwd=None) as env:
        assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_a_github_push_carries_the_stored_token_as_a_scoped_header(
    monkeypatch, stored_token,
):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: HTTPS_ORIGIN)
    with cg.git_environment(["-C", "/repo", "push", "origin", "main"], cwd=None) as env:
        values = _config_values(env)
        # The key is reset before it is set, so an ambient value for the same
        # URL cannot survive alongside the one this environment injects.
        header = values[f"http.{HTTPS_ORIGIN}.extraheader"]
        assert header == [
            "", "AUTHORIZATION: basic " + _expected_basic(stored_token),
        ]
        assert values["credential.helper"] == [""]
        # The hermetic environment is what keeps an ambient helper, a global
        # config, or a stray netrc from answering for this push instead.
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["HOME"] != ""
        assert env["GIT_ALLOW_PROTOCOL"] == "https"


def _expected_basic(token: str) -> str:
    import base64

    return base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")


def test_an_ssh_origin_is_rewritten_onto_https_so_the_token_serves_it(
    monkeypatch, stored_token,
):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: SSH_ORIGIN)
    with cg.git_environment(["-C", "/repo", "fetch", "origin"], cwd=None) as env:
        values = _config_values(env)
        rewrites = values["url.https://github.com/.insteadOf"]
        assert rewrites == ["git@github.com:", "ssh://git@github.com/"]
        assert f"http.{HTTPS_ORIGIN}.extraheader" in values


def test_no_credential_refuses_by_name_with_its_recovery(monkeypatch):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: HTTPS_ORIGIN)

    def _unavailable():
        raise RuntimeError("machine GitHub App authorization is not configured")

    monkeypatch.setattr(
        "yoke_cli.config.github_local_user_access.access_token", _unavailable,
    )
    with pytest.raises(cg.CredentialedGitError) as excinfo:
        with cg.git_environment(["-C", "/repo", "push", "origin", "main"]):
            pass
    message = str(excinfo.value)
    assert "not configured" in message
    assert "yoke github connect" in message
    assert HTTPS_ORIGIN in message


def test_run_reports_a_refusal_as_a_failed_command_not_a_crash(monkeypatch):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: HTTPS_ORIGIN)

    def _refuse(url):
        raise cg.CredentialedGitError("no credential. run `yoke github connect`")

    monkeypatch.setattr(cg, "resolve_token", _refuse)
    result = cg.run(["-C", "/repo", "push", "origin", "main"])
    assert result.returncode == cg.REFUSAL_EXIT_CODE
    assert "yoke github connect" in result.stderr
    assert result.stdout == ""


def test_run_with_check_raises_the_refusal_for_callers_that_want_it(monkeypatch):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: HTTPS_ORIGIN)
    monkeypatch.setattr(
        cg,
        "resolve_token",
        lambda url: (_ for _ in ()).throw(cg.CredentialedGitError("nope")),
    )
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        cg.run(["-C", "/repo", "push", "origin", "main"], check=True)
    assert excinfo.value.returncode == cg.REFUSAL_EXIT_CODE


def test_run_executes_a_local_command_and_returns_its_output(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    result = cg.run(["rev-parse", "--is-inside-work-tree"], cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_a_timeout_names_what_stalled_instead_of_reading_as_a_hang(monkeypatch):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: "")

    def _timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 15)

    monkeypatch.setattr(subprocess, "run", _timeout)
    result = cg.run(["-C", "/repo", "fetch", "origin"], timeout=15)
    assert result.returncode == cg.TIMEOUT_EXIT_CODE
    assert "did not finish within 15s" in result.stderr
    assert "cannot be waiting on a prompt" in result.stderr


def test_a_cached_token_is_reused_until_it_nears_expiry(monkeypatch):
    calls: list[int] = []

    def _access_token():
        calls.append(1)
        return _Token("gho_live")

    monkeypatch.setattr(
        "yoke_cli.config.github_local_user_access.access_token", _access_token,
    )
    assert cg.resolve_token(HTTPS_ORIGIN) == "gho_live"
    assert cg.resolve_token(HTTPS_ORIGIN) == "gho_live"
    assert len(calls) == 1


def test_a_token_inside_the_refresh_margin_is_read_again(monkeypatch):
    calls: list[int] = []

    def _access_token():
        calls.append(1)
        return _Token("gho_live", expires_in_seconds=30)

    monkeypatch.setattr(
        "yoke_cli.config.github_local_user_access.access_token", _access_token,
    )
    cg.resolve_token(HTTPS_ORIGIN)
    cg.resolve_token(HTTPS_ORIGIN)
    assert len(calls) == 2


def test_a_failed_credentialed_command_says_the_credential_was_applied(
    monkeypatch, stored_token,
):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(cgc, "remote_url", lambda repo, remote: HTTPS_ORIGIN)

    def _fail(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 128, "", "fatal: unable to get password from user",
        )

    monkeypatch.setattr(subprocess, "run", _fail)
    result = cg.run(["-C", "/repo", "push", "origin", "main"])
    assert result.returncode == 128
    assert "unable to get password" in result.stderr
    # Without this line the same git error reads identically whether Yoke
    # supplied a credential the remote rejected or supplied none at all.
    assert "credential WAS applied" in result.stderr
    assert HTTPS_ORIGIN in result.stderr


def test_a_failed_uncredentialed_command_says_why_none_was_applied(monkeypatch):
    monkeypatch.setattr(cg, "configured_web_url", lambda: WEB_URL)
    monkeypatch.setattr(
        cgc, "remote_url", lambda repo, remote: "https://gitlab.example/a/b.git",
    )

    def _fail(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 128, "", "fatal: repository not found")

    monkeypatch.setattr(subprocess, "run", _fail)
    result = cg.run(["-C", "/repo", "fetch", "origin"])
    assert "No credential was applied" in result.stderr
    assert "not this machine's configured GitHub origin" in result.stderr


def test_a_failed_local_command_gets_no_credential_attribution(monkeypatch):
    def _fail(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", _fail)
    result = cg.run(["-C", "/repo", "status"])
    assert result.stderr == "fatal: not a git repository"
