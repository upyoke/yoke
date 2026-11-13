"""``cd $VAR`` resolves through assignments written before it (note 95045).

A lane or temp directory named through a variable must not fall back to the
session folder (main), and a variable bound only after the ``cd`` must not
move it either.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime.api.domain.test_lint_lane_main_write_workdir import (  # noqa: F401
    _evaluate,
    lane_repo,
)
from yoke_contracts.hook_runner.command_extract import substitute_bound_variables
from yoke_contracts.hook_runner.shell_parse import advance_cwd, parse_shell
from yoke_core.domain.command_workdir import (
    command_execution_cwd,
    command_segment_cwds,
)
from yoke_core.domain.lint_shell_target_tokens import (
    is_assignment_statement,
    segment_variable_bindings,
)


def _payload(command: str, cwd: str) -> dict:
    return {"cwd": cwd, "tool_input": {"command": command}}


def _resolved(path) -> str:
    return str(Path(path).resolve())


def test_mktemp_bound_cd_moves_the_execution_cwd(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = 'S=$(mktemp -d); cd $S/out && echo x > f.py'
    expected = _resolved(Path(tempfile.gettempdir()) / "tmp.XXXXXXXXXX" / "out")
    assert command_execution_cwd(_payload(command, str(main))) == expected


def test_mktemp_bound_cd_moves_later_segments(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = 'echo start; S=$(mktemp -d /tmp/lane.XXXXXX); cd "$S"; echo x > f.py'
    cwd, segment_cwds = command_segment_cwds(_payload(command, str(main)))
    assert cwd == _resolved(main)
    assert segment_cwds[-1] == _resolved("/tmp/lane.XXXXXX")


def test_literal_lane_variable_cd_resolves_to_the_lane(tmp_path):
    lane = tmp_path / "main" / ".worktrees" / "YOK-1"
    lane.mkdir(parents=True)
    command = f"L={lane}; cd ${{L}} && echo x > f.py"
    assert command_execution_cwd(_payload(command, str(tmp_path / "main"))) == (
        _resolved(lane)
    )


def test_variable_naming_main_still_resolves_to_main(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = f"S={main}; cd $S; echo x > f.py"
    assert command_execution_cwd(_payload(command, str(tmp_path))) == _resolved(main)


def test_variable_bound_after_the_cd_does_not_move_it(tmp_path):
    main = tmp_path / "main"
    lane = main / ".worktrees" / "YOK-1"
    lane.mkdir(parents=True)
    command = f"cd $S && echo x>f.py; S={lane}"
    payload = _payload(command, str(main))
    assert command_execution_cwd(payload) == _resolved(main)
    cwd, segment_cwds = command_segment_cwds(payload)
    assert cwd == _resolved(main)
    assert segment_cwds[1] == ""


def test_mktemp_bound_after_the_cd_does_not_move_it(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = "cd $S && echo x>f.py; S=$(mktemp -d)"
    assert command_execution_cwd(_payload(command, str(main))) == _resolved(main)


def test_unbound_variable_cd_keeps_the_declared_cwd(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = "cd $UNKNOWN && echo x > f.py"
    assert command_execution_cwd(_payload(command, str(main))) == _resolved(main)


def test_reassignment_to_an_opaque_value_drops_the_binding(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    command = "S=$(mktemp -d); S=$(date +%s); cd $S; echo x > f.py"
    assert command_execution_cwd(_payload(command, str(main))) == _resolved(main)


def test_substitution_only_uses_earlier_assignments():
    assert substitute_bound_variables("cd $S; S=/lane") == "cd $S; S=/lane"
    assert substitute_bound_variables("S=/a; cd $S; S=/b; cd $S") == (
        "S=/a; cd /a; S=/b; cd /b"
    )
    assert substitute_bound_variables("S=/a; S=; cd $S") == "S=/a; S=; cd $S"


def test_segment_bindings_hold_only_prior_statements():
    parsed = parse_shell("cd $S; S=/lane; cd $S")
    bindings = segment_variable_bindings([s.text for s in parsed.segments])
    assert bindings == [{}, {}, {"S": "/lane"}]


def test_advance_cwd_without_bindings_is_unchanged():
    assert advance_cwd("/repo", "$S") == ""
    assert advance_cwd("/repo", "$S", bindings={"S": "/tmp/x"}) == _resolved("/tmp/x")
    assert advance_cwd("/repo", "$S/$T", bindings={"S": "/tmp/x"}) == ""


def test_assignment_statements_run_nothing():
    assert is_assignment_statement("S=$(mktemp -d)")
    assert is_assignment_statement('S="$(mktemp -d)" T=/x')
    assert not is_assignment_statement("S=/x echo hi")
    assert not is_assignment_statement("export S=/x")


@pytest.mark.parametrize(
    "command",
    [
        "L={lane}; cd $L && echo x > f.py",
        "S=$(mktemp -d); cd $S && echo x > f.py",
    ],
)
def test_guard_allows_a_variable_cd_out_of_main(lane_repo, command):
    repo, lane = lane_repo
    verdict = _evaluate(command.format(lane=lane), cwd=repo)
    assert verdict.allow is True, verdict.reason


@pytest.mark.parametrize(
    "command, cwd_is_lane",
    [
        ("S={repo}; cd $S; echo x > f.py", True),
        ("cd $S && echo x > f.py; S={lane}", False),
        ("cd $UNKNOWN && echo x > f.py", False),
    ],
)
def test_guard_still_denies_main_writes(lane_repo, command, cwd_is_lane):
    repo, lane = lane_repo
    verdict = _evaluate(
        command.format(repo=repo, lane=lane), cwd=lane if cwd_is_lane else repo
    )
    assert verdict.allow is False
