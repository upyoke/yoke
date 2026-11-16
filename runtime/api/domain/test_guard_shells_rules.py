"""Each shell-chain rule's Bash case and PowerShell case.

A rule that covers both shells refuses the PowerShell spelling of the same
act; a Bash-only rule still refuses its Bash idiom and never runs on a
PowerShell command. Rules whose verdict needs claims or a repository are
checked at the seam that reads the command.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import mock

import pytest

from yoke_contracts.hook_runner.guard_shells import GUARD_SHELLS, shell_applicable_chain
from yoke_core.hooks.types import HookContext, Outcome

pytestmark = pytest.mark.windows

_D = "yoke_core.domain."
_MAIN_COMMIT_FACTS = {
    "_yoke_client_git_commit_facts": {
        "schema": 1, "is_git_commit": True, "repo_cwd": "/client/checkout",
        "branch": "main", "staged_paths": ["runtime/api/domain/foo.py"],
        "staged_probe_ok": True, "status_probe_ok": True,
    }
}
_HEADLESS = {"_yoke_client_headless_launch": {"schema": 1, "value": True}}
_SWEEP = "python3 -m pytest runtime/api/ runtime/harness/ tests/"

# module, Bash command, PowerShell command, extra payload fields.
_COVERS_BOTH = [
    ("lint_db_cmd", 'sqlite3 "$YOKE_DB" "SELECT 1"', "sqlite3 $env:YOKE_DB 'SELECT 1'", {}),
    ("lint_main_commit", "git commit -m 'wip'", 'git commit -m "wip"', _MAIN_COMMIT_FACTS),
    ("lint_raw_pytest_full_suite", f"uv run --frozen {_SWEEP}", f"& uv run --frozen {_SWEEP}", {}),
    ("lint_watcher_module_form", "python3 -m yoke_core.tools.watch_pytest",
     "& python3 -m yoke_core.tools.watch_pytest", {}),
    ("lint_headless_watcher_timeout", "yoke watch pytest --impacted main --bounded",
     "yoke watch pytest --impacted main --bounded", _HEADLESS),
    ("lint_subagent_background", "python3 -m foo", "python3 -m foo",
     {"agent_type": "engineer", "run_in_background": True}),
    ("lint_subagent_fleet_messaging", "yoke messages ack message-id",
     "& 'C:\\Tools\\yoke.exe' messages ack message-id", {"agent_type": "engineer"}),
    ("lint_no_agent_runtime_api_import_from_c",
     'python3 -c "from yoke_core.domain.events import emit"',
     "python3 -c 'from yoke_core.domain.events import emit'", {}),
    ("lint_no_agent_curl_against_yoke_api", "curl http://localhost:8765/v1/health",
     "curl.exe http://localhost:8765/v1/health", {}),
    ("lint_no_agent_session_end", "python3 -m yoke_core.api.service_client session-end",
     "Write-Output go; python3 -m yoke_core.api.service_client session-end", {}),
    ("lint_claim_ownership_mutations",
     "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1 --session-id sess-other",
     "$env:X = '1'; python3 -m yoke_core.api.service_client release-work-claim --item YOK-1 --session-id sess-other",
     {}),
    ("lint_git_stash_arg_order", 'git stash push -u -- a.txt -m "reason"',
     "git stash push -u -- a.txt -m 'reason'", {}),
    ("lint_tc_label", 'printf "TC-5" > .agents/skills/yoke/scripts/tests/test-x.sh',
     "'TC-5' > .agents/skills/yoke/scripts/tests/test-x.sh", {}),
]

_COVERS_BASH = [
    ("lint_long_command_polling", "until yoke messages list --unread | grep -q 'QA ready'; do sleep 20; done",
     "while ($true) { yoke messages list --unread; Start-Sleep 20 }"),
    ("lint_pipe_to_truncator", "python3 -m pytest -q | tail -2",
     "python3 -m pytest -q | Select-Object -Last 2"),
    ("lint_if_status_capture", "if false; then echo ok; fi; rc=$? # lint:no-if-status-capture-check",
     "if (-not $ok) { exit 0 }; $rc = $?"),
    ("lint_structured_field_transform_shell",
     "items get 42 spec > /tmp/old.md && items update 42 spec --stdin < /tmp/new.md",
     "items get 42 spec > $env:TEMP\\old.md; Get-Content $env:TEMP\\new.md | items update 42 spec --stdin"),
    ("lint_yoke_adapter_stderr_visibility",
     "yoke say --stdin 2>/dev/null # lint:no-yoke-adapter-stderr-visibility-check",
     "yoke say --stdin 2>$null"),
    ("lint_shell_backtick_search", "rg \"uses `foo` here\" docs/  # lint:no-backtick-search-check",
     'rg "uses `"foo`" here" docs/'),
    ("lint_yoke_quoted_shell_substitution",
     'yoke dash --title "run `whoami`"  # lint:no-yoke-quoted-substitution-check',
     'yoke dash --title "run $(whoami)"'),
    ("lint_unmatched_path_glob", "rg -rn PAT docs", "rg -rn PAT docs"),
    ("lint_local_privacy", "cat '/Library/Application Support/com.apple.TCC/TCC.db'",
     "Get-Content 'C:\\Users\\me\\AppData\\Local\\secret.db'"),
]


def _context(command: str, shell: str, extra: dict) -> HookContext:
    tool_input = {"command": command}
    if extra.get("run_in_background"):
        tool_input["run_in_background"] = True
    payload = {
        "tool_name": "Bash",
        "tool_input": tool_input,
        "session_id": "sess-self",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
        "cwd": "/client/checkout",
        "yoke_shell_kind": shell,
        **{k: v for k, v in extra.items() if k != "run_in_background"},
    }
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="cli",
        payload=payload,
        tool_name="Bash",
        command_body=command,
        cwd="/client/checkout",
        session_id="sess-self",
    )


def _decide(name: str, ctx: HookContext) -> Outcome:
    module_id = _D + name
    if module_id not in shell_applicable_chain([module_id], ctx.shell_kind):
        return Outcome.NOOP
    module = importlib.import_module(module_id)
    with mock.patch.dict("os.environ", {"YOKE_DB": ""}):
        if name == "lint_main_commit":
            with mock.patch.object(module, "_active_worktree_items", return_value=["YOK-7|x"]):
                return module.evaluate(ctx).outcome
        return module.evaluate(ctx).outcome


def test_tables_cover_every_declared_command_rule() -> None:
    named = {row[0] for row in _COVERS_BOTH} | {row[0] for row in _COVERS_BASH}
    seams = {"lint_session_cwd", "lint_lane_main_write", "lint_workspace_cwd_match",
             "path_claim_bash_guard", "lint_destructive_git", "db_error_hook",
             "observe_pre", "observe"}
    assert named | seams == {m.removeprefix(_D) for m in GUARD_SHELLS}
    assert all("powershell" in GUARD_SHELLS[_D + r[0]] for r in _COVERS_BOTH)
    assert all("powershell" not in GUARD_SHELLS[_D + r[0]] for r in _COVERS_BASH)


@pytest.mark.parametrize(("name", "bash", "powershell", "extra"), _COVERS_BOTH)
def test_rule_refuses_both_spellings(name, bash, powershell, extra) -> None:
    assert _decide(name, _context(bash, "bash", extra)) is Outcome.DENY
    assert _decide(name, _context(powershell, "powershell", extra)) is Outcome.DENY


@pytest.mark.parametrize(("name", "bash", "powershell"), _COVERS_BASH)
def test_bash_idiom_rule_skips_powershell(name, bash, powershell) -> None:
    assert _decide(name, _context(bash, "bash", {})) is Outcome.DENY
    assert _decide(name, _context(powershell, "powershell", {})) is Outcome.NOOP


# --- Rules whose verdict needs claims, a repository or a tool response ------


def _payload(command: str, shell: str, **extra) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command},
            "yoke_shell_kind": shell, "session_id": "sess-self", **extra}


@pytest.mark.parametrize(
    ("bash", "powershell"),
    [("printf x > src/a.py", "Set-Content src/a.py x"), ("rm src/a.py", "Remove-Item src/a.py")],
)
def test_session_cwd_and_lane_write_read_the_same_targets(bash, powershell) -> None:
    from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
    from yoke_core.domain.lint_session_cwd_target_extract import analyze_payload_write_targets

    for command, shell in ((bash, "bash"), (powershell, "powershell")):
        payload = _payload(command, shell, cwd="/repo")
        assert is_write_operation("Bash", payload), (shell, command)
        assert analyze_payload_write_targets(payload).targets == ["src/a.py"], shell
    assert not is_write_operation("Bash", _payload("Get-Content src/a.py", "powershell"))


def test_workspace_cwd_match_refuses_a_writer_outside_the_lane_in_both_shells(tmp_path) -> None:
    from yoke_core.domain import lint_workspace_cwd_match as rule

    lane, main = (tmp_path / "lane").resolve(), (tmp_path / "main").resolve()
    with mock.patch.object(rule, "resolve_session_worktree_paths", return_value=[str(lane)]):
        for command, shell in (
            (f"cd {main.as_posix()} && pytest tests/test_x.py", "bash"),
            (f"Set-Location '{main}'; pytest tests/test_x.py", "powershell"),
        ):
            assert rule.evaluate_payload(_payload(command, shell, cwd=str(lane))), shell
        writer = _payload("pytest tests/test_x.py", "powershell", cwd=str(lane))
        assert rule.evaluate_payload(writer) is None


def test_path_claim_guard_reads_both_shells() -> None:
    from yoke_core.domain.path_claim_bash_parser import extract_mutations
    from yoke_core.domain.path_claim_powershell_parser import extract_powershell_mutations

    bash = extract_mutations("printf x > src/a.py", "/repo")
    powershell = extract_powershell_mutations("Out-File -FilePath src/a.py", "/repo")
    assert [m.target_path for m in bash] == [m.target_path for m in powershell] == ["src/a.py"]


def test_destructive_git_refuses_reset_hard_in_both_shells() -> None:
    from runtime.api.domain.destructive_git_test_helpers import _make_repo, _modify

    repo = _make_repo(initial_files={"a.txt": "v1\n"})
    _modify(repo, "a.txt", "v2\n")
    for command, shell in (
        # Bash (Git Bash on Windows) is written with forward slashes.
        (f"git -C {Path(repo).as_posix()} reset --hard HEAD~1", "bash"),
        (f"git -C '{repo}' reset --hard HEAD~1", "powershell"),
    ):
        assert _decide("lint_destructive_git", _context(command, shell, {})) is Outcome.DENY


def test_db_error_hook_advises_on_a_failed_query_in_both_shells() -> None:
    from yoke_core.domain import db_error_hook

    for command, shell in (('sqlite3 x.db "select"', "bash"), ("sqlite3 x.db 'select'", "powershell")):
        ctx = HookContext(
            event_name="PostToolUse", executor_family="claude", executor_surface="cli",
            payload={**_payload(command, shell), "tool_response": "Exit code 1"},
            tool_name="Bash", session_id="sess-self",
        )
        assert shell_applicable_chain([_D + "db_error_hook"], ctx.shell_kind)
        assert "HARD STOP" in db_error_hook.evaluate(ctx).audit_fields.get("additionalContext", ""), shell


def test_observation_records_the_command_in_both_shells() -> None:
    from yoke_core.domain.observe_parsing import parse_hook_event

    for command, shell in (("git status", "bash"), ("Get-ChildItem; git status", "powershell")):
        assert shell_applicable_chain([_D + "observe", _D + "observe_pre"], shell)
        record = parse_hook_event({**_payload(command, shell), "tool_response": "ok"}, hook_event="PostToolUse")
        assert record is not None and command in str(record), shell
