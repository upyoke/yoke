"""Whole-disk scans are refused by name on both hook paths, identically.

``find / -name x`` ran for 23-46 minutes with no output in two sessions and
blocked their turns, so Yoke messages could not reach them. The engine
guard and the client-local guard share one classifier; these cases pin the
refusals, the allowed searches, parity, and the client denial row.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from yoke_contracts.hook_runner.bash_paths import client_path_scope
from yoke_contracts.hook_runner.broad_filesystem_scan import (
    CHECK_ID,
    find_broad_scan,
)
from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_core.api.routes.hooks_denial_audit import (
    HookDenialAuditRequest,
    post_hooks_denial_audit,
)
from yoke_core.domain import lint_broad_filesystem_scan as engine
from yoke_core.hooks import denial
from yoke_core.hooks.types import HookContext, Outcome
from yoke_harness.hooks import local_subset
from yoke_harness.hooks.broad_filesystem_scan import lint_broad_filesystem_scan
from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.local_policy_common import DENY

CHECKOUT = str(Path(__file__).resolve().parents[3])

REFUSED = [
    ("find / -name x", "/"),
    ("find / -path '*/foo' -name x -print", "/"),
    ("bfs / -name x", "/"),
    ("fd x /", "/"),
    ("fd x /Users", "/Users"),
    ("find /System -name x", "/System"),
    ("find /Users/ -name x", "/Users/"),
    ("find -L /Volumes -name x", "/Volumes"),
    ("du -sh /private", "/private"),
    ("rg --files / -g x", "/"),
    ("grep -rn needle /", "/"),
    ("fd -e py x --search-path /", "/"),
    ("sudo find / -name x", "/"),
    ("cd / && find . -name x", "."),
    ("bash -c 'find / -name x'", "/"),
    ("zsh -c 'find / -name x 2>/dev/null'", "/"),
    ("ls && find /* -name x", "/*"),
    ("mdfind -onlyin / x", "/"),
    ("ls -R /", "/"),
    ("tree /Users", "/Users"),
]
REFUSED_INDEX = ["locate x", "mdfind x", "plocate x"]
ALLOWED = [
    "find . -name x",
    f"find {CHECKOUT} -name x",
    "find /tmp -name x",
    "find ~ -name x",
    "rg --files -g x",
    f"mdfind -onlyin {CHECKOUT} x",
    "ls /",
    "ls -la /Users",
    "fd x",
    "find /Users/someone/project -name x",
    "echo 'find / -name x'",
    "grep needle /etc/hosts",
]


WINDOWS_HOME = "C:\\Users\\me"
WINDOWS_REPO = "C:\\Users\\me\\repo"
# Git Bash maps `/` to its install directory and `/c` to the drive; the
# second fact set has no mount table, so `/` and `/c` cannot resolve at all.
WINDOWS_FACTS = [
    {
        "windows": True,
        "home": WINDOWS_HOME,
        "mount_paths": {"/": "C:\\Program Files\\Git", "/c": "C:\\"},
    },
    {"windows": True, "home": WINDOWS_HOME},
]
WINDOWS_REFUSED = [
    "find / -name x",
    "find /Users -name x",
    "find /c -name x",
    "find /c/ -name x",
    "find /D -name x",
    "find /c/Users -name x",
    "find C:/ -name x",
    "find C:/Users -name x",
    "bash -c 'find /c -name x'",
]
WINDOWS_ALLOWED = [
    "find /c/Users/me/repo -name x",
    "find C:/Users/me/repo -name x",
    "find . -name x",
    "fd x",
]


def _payload(command: str, cwd: str = CHECKOUT) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": "sid-broad-scan",
        "tool_use_id": "tu-broad-scan",
    }


def _engine(command: str, cwd: str = CHECKOUT):
    payload = _payload(command, cwd)
    return engine.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload=payload,
            tool_name="Bash",
            command_body=command,
            cwd=cwd,
        )
    )


def _client(command: str, cwd: str = CHECKOUT):
    return lint_broad_filesystem_scan(_payload(command, cwd), parse_shell(command))


@pytest.mark.parametrize("command,root", REFUSED)
def test_whole_disk_roots_are_refused_naming_root_and_recovery(command, root) -> None:
    decision = _engine(command)
    assert decision.outcome is Outcome.DENY
    assert decision.block is True
    assert f"`{root}`" in decision.message
    assert f"Yoke check id: {CHECK_ID}" in decision.message
    assert "rg --files -g 'NAME'" in decision.message
    assert "print(m.__file__)" in decision.message
    assert decision.audit_fields["check_id"] == CHECK_ID


@pytest.mark.parametrize("command", REFUSED_INDEX)
def test_index_searchers_without_onlyin_are_refused(command) -> None:
    decision = _engine(command)
    assert decision.outcome is Outcome.DENY
    assert "mdfind -onlyin <checkout> NAME" in decision.message


@pytest.mark.parametrize("command", ALLOWED)
def test_scoped_searches_are_allowed(command) -> None:
    assert _engine(command).outcome is Outcome.NOOP


def test_implicit_cwd_root_is_refused_only_at_a_whole_disk_root() -> None:
    assert _engine("find -name x", cwd="/").outcome is Outcome.DENY
    assert _engine("fd x", cwd="/Users").outcome is Outcome.DENY
    assert _engine("find -name x", cwd=CHECKOUT).outcome is Outcome.NOOP


@pytest.mark.parametrize(
    "command",
    [c for c, _ in REFUSED] + REFUSED_INDEX + ALLOWED,
)
def test_engine_and_client_decide_identically(command) -> None:
    core = _engine(command)
    client = _client(command)
    assert (core.outcome is Outcome.DENY) == (client.outcome == DENY)
    if client.outcome == DENY:
        assert client.message == core.message


@pytest.mark.parametrize("facts", WINDOWS_FACTS)
@pytest.mark.parametrize("cwd", [WINDOWS_REPO, None])
@pytest.mark.parametrize("command", WINDOWS_REFUSED)
def test_git_bash_whole_disk_roots_are_refused_before_mount_mapping(
    command, cwd, facts
) -> None:
    with client_path_scope(facts):
        scan = find_broad_scan(command, cwd=cwd, home=WINDOWS_HOME)
    assert scan is not None and scan.tool == "find"


@pytest.mark.parametrize("command", WINDOWS_ALLOWED)
def test_git_bash_repo_scoped_searches_are_allowed(command) -> None:
    with client_path_scope(WINDOWS_FACTS[0]):
        assert find_broad_scan(command, cwd=WINDOWS_REPO, home=WINDOWS_HOME) is None


@pytest.mark.parametrize("cwd", ["C:\\", "C:\\Users"])
def test_git_bash_implicit_cwd_at_a_drive_root_is_refused(cwd) -> None:
    with client_path_scope(WINDOWS_FACTS[0]):
        assert find_broad_scan("find -name x", cwd=cwd, home=WINDOWS_HOME)


@pytest.mark.parametrize(
    "command",
    ["cd / && find . -name x", "cd / && find -name x", "cd /Users && find . -name x"],
)
def test_git_bash_cd_to_a_whole_disk_root_is_refused_before_mount_mapping(
    command,
) -> None:
    # `cd /` resolves to the Git Bash install directory, so only the
    # directory as written shows the scan walks the whole disk.
    with client_path_scope(WINDOWS_FACTS[0]):
        scan = find_broad_scan(command, cwd=WINDOWS_REPO, home=WINDOWS_HOME)
    assert scan is not None and scan.tool == "find"


def test_git_bash_cd_into_a_repo_still_allows_a_relative_scan() -> None:
    with client_path_scope(WINDOWS_FACTS[0]):
        assert (
            find_broad_scan(
                "cd /c/Users/me/repo && find . -name x",
                cwd=WINDOWS_REPO,
                home=WINDOWS_HOME,
            )
            is None
        )


def test_drive_mounts_stay_scoped_on_posix_clients() -> None:
    with client_path_scope({"windows": False, "home": "/Users/me"}):
        assert find_broad_scan("find /c -name x", cwd="/repo", home="/Users/me") is None
        assert find_broad_scan("find / -name x", cwd="/repo", home="/Users/me")


def test_guard_is_registered_deny_by_default_and_unprotected() -> None:
    spec = next(s for s in GUARD_CATALOG if s.guard == "lint_broad_filesystem_scan")
    assert spec.check_id == CHECK_ID
    assert spec.module == "yoke_core.domain.lint_broad_filesystem_scan"
    assert spec.protected is False


def test_client_refusal_records_a_denial_row_with_the_check_id(tmp_path) -> None:
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(_payload("find / -name x", cwd=str(tmp_path))),
        "codex",
        None,
        start_hook_deadline(),
        lint_config_snapshot={},
    )
    assert result.denied is True
    assert CHECK_ID in result.stdout
    audit = result.denial_audit
    assert audit["check_id"] == CHECK_ID
    assert audit["session_id"] == "sid-broad-scan"

    with (
        mock.patch("yoke_core.api.routes.hooks_denial_audit.require_auth_context"),
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
    ):
        post_hooks_denial_audit(object(), HookDenialAuditRequest(**audit))
    forwarded = canonical.call_args.kwargs
    assert forwarded["check_id"] == CHECK_ID
    with (
        mock.patch.object(denial, "_close_denied_call"),
        mock.patch("yoke_core.domain.emit_event.emit") as emit,
    ):
        denial.emit_denial_event(**forwarded)
    event = emit.call_args.args[0]
    assert event.name == denial.DENIAL_EVENT_NAME
    assert event.session_id == "sid-broad-scan"
    assert json.loads(event.context)["check_id"] == CHECK_ID


def test_warn_mode_lets_the_scan_through_with_context(tmp_path) -> None:
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(_payload("find / -name x", cwd=str(tmp_path))),
        "claude",
        None,
        start_hook_deadline(),
        lint_config_snapshot={"lint_broad_filesystem_scan": {"mode": "warn"}},
    )
    assert result.denied is False
