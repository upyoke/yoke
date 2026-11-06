"""Input roles admit file reads without granting unknown programs authority."""

import shlex
from types import SimpleNamespace

import pytest

from yoke_core.domain import lint_session_cwd_validate as validator
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    governed_targets, is_read_only_git_inspection,
)
from yoke_core.domain.lint_session_cwd_git_read_forms import classify_git
from yoke_core.domain.lint_shell_path_use import PathRole, analyze_shell_path_use
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

OWN = "/repo/.worktrees/own"
FOREIGN = "/repo/.worktrees/other"
INPUT = "/repo/.worktrees/unclaimed/input.json"


@pytest.fixture
def validate(monkeypatch):
    monkeypatch.setattr(validator, "claimed_worktrees", lambda *a, **k: [
        ClaimedWorktree(1, None, OWN)
    ])
    monkeypatch.setattr(validator, "_recorded_repo_roots", lambda *a: ["/repo"])
    monkeypatch.setattr(validator, "occupying_claim", lambda *a, target, **k:
        SimpleNamespace() if target.startswith(FOREIGN) else None)

    def run(command, tool_name="Bash"):
        analysis = analyze_shell_path_use(command)
        return validator.validate_targets(
            None, session_id="reader", targets=analysis.local_targets,
            fallback_cwd=OWN, tool_name=tool_name, command=command,
            read_only=not analysis.direct_write, path_uses=analysis.uses,
        )
    return run


@pytest.mark.parametrize("flag", [f"--content-file {INPUT}", f"--content-file={INPUT}"])
def test_content_file_is_a_read_even_when_the_adapter_mutates_records(validate, flag):
    command = f"yoke qa artifact add --case-id 1 {flag}"
    uses = analyze_shell_path_use(command).uses
    assert {use.role for use in uses if use.path == INPUT} == {PathRole.READ}
    assert validate(command).allow


def test_record_adapter_keeps_foreign_lane_occupancy_checks(validate):
    assert not validate(f"yoke qa artifact add --content-file {FOREIGN}/input.json").allow


def test_unknown_program_in_a_foreign_working_directory_stays_refused(validate):
    assert not validate(f"cd {FOREIGN} && ./build.sh").allow


@pytest.mark.parametrize("program", ["./build.sh", "python x.py"])
def test_unknown_program_with_foreign_path_stays_refused(validate, program):
    assert not validate(f"{program} {FOREIGN}/input.json").allow
    assert not validate(f"{program} {INPUT}").allow


@pytest.mark.parametrize("command", [
    f"cat {INPUT} > {INPUT}",
    f"yoke qa artifact add --content-file {INPUT} > {INPUT}",
    f"cp {OWN}/input.json {FOREIGN}/input.json",
])
def test_writes_cannot_inherit_a_read_exemption(validate, command):
    assert not validate(command).allow


@pytest.mark.parametrize("command", [
    f'git -C {FOREIGN} grep "/docs/start"',
    f'git -C {FOREIGN} grep -n -- "/docs/start"',
])
def test_git_grep_reads_an_occupied_lane(validate, command):
    assert classify_git(shlex.split(command)) == "git-grep"
    assert is_read_only_git_inspection(command)
    assert governed_targets([FOREIGN], ["/repo"], command) == []
    assert validate(command).allow


@pytest.mark.parametrize("option", ["-O", "-Ofoo"] + [
    "--open-files-in-pager"[:length]
    for length in range(3, len("--open-files-in-pager") + 1)
] + ["--open=foo", "--open-files-in-pager=foo"])
def test_git_grep_pager_forms_are_not_foreign_lane_inspection(validate, option):
    command = f"git -C {FOREIGN} grep {option} /docs/start"
    assert classify_git(shlex.split(command)) is None
    assert not is_read_only_git_inspection(command)
    assert governed_targets([FOREIGN], ["/repo"], command) == [FOREIGN]
    assert not validate(command).allow


@pytest.mark.parametrize("other_use", [INPUT, f"--output {INPUT}"])
def test_an_input_path_reused_as_an_unknown_operand_keeps_scope_checks(validate, other_use):
    command = f"yoke qa artifact add --content-file {INPUT} {other_use}"
    assert not validate(command).allow


@pytest.mark.parametrize("command", [
    f"yoke dev run -- python x.py --content-file {INPUT}",
    f"yoke qa artifact add -- --content-file {INPUT}",
])
def test_content_file_after_option_terminator_grants_no_read_authority(validate, command):
    assert not validate(command).allow


def test_read_role_without_a_declared_tool_keeps_scope_checks(validate):
    assert not validate(
        f"yoke qa artifact add --content-file {INPUT}", tool_name=""
    ).allow
