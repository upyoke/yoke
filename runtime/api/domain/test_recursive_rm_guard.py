"""Recursive ``rm`` refusals shared by the client and engine destructive guards.

The incident: an audit subagent rebuilt a ``mktemp -d`` parent in a later
Bash call and ran ``rm -rf "$(dirname $(mktemp -u))"/tmp.*``, deleting every
session's ``tmp.*`` entry in the shared macOS temp dir.
"""

from __future__ import annotations

import pytest

from yoke_contracts.hook_runner import recursive_rm_guard as guard
from yoke_contracts.hook_runner.destructive_git_messages import (
    format_recursive_rm_reason,
)
from yoke_core.domain import lint_destructive_git as engine
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_harness.hooks import local_policies

INCIDENT = 'rm -rf "$(dirname $(mktemp -u))"/tmp.* 2>/dev/null'


@pytest.fixture
def roots(tmp_path, monkeypatch):
    shared = tmp_path / "shared-tmp"
    scratch = shared / "yoke-scratch"
    scratch.mkdir(parents=True)
    values = [str(shared), str(scratch)]
    monkeypatch.setattr(guard, "scratch_path_roots", lambda: values)
    return shared, scratch


def _shape(command: str, cwd: str = "/") -> str | None:
    refusal = guard.recursive_rm_refusal(command, cwd)
    return refusal.shape if refusal else None


def test_incident_command_is_refused_as_unresolved(roots):
    assert _shape(INCIDENT) == guard.UNRESOLVED_SHAPE


@pytest.mark.parametrize(
    "command",
    [
        'rm -rf "$T"',
        "rm -r $DIR/build",
        'rm -rf "${HOME}/x"',
        "rm -rf `pwd`/out",
        'T=$(cat path.txt); rm -rf "$T"',
        'for d in a b; do rm -rf "$d"; done',
    ],
)
def test_unresolved_targets_are_refused(roots, command):
    assert _shape(command) == guard.UNRESOLVED_SHAPE


@pytest.mark.parametrize(
    "command",
    [
        'T=$(mktemp -d); trap \'rm -rf "$T"\' EXIT; echo hi > "$T/x"; rm -rf "$T"',
        'T="$(mktemp -d)" && rm -rf "$T"',
        "T=$(mktemp -d /tmp/work.XXXXXX)\nls \"$T\"\nrm -rf \"${T}\"",
    ],
)
def test_mktemp_dir_removed_in_its_creating_call_passes(roots, command):
    assert _shape(command) is None


def test_literal_assignment_resolves_before_checking(roots):
    shared, _ = roots
    assert _shape(f'D={shared}/mine; rm -rf "$D"') is None
    assert _shape(f'D={shared}; rm -rf "$D"/*') == guard.SHARED_TEMP_SHAPE


def test_shared_temp_glob_is_refused(roots):
    shared, scratch = roots
    assert _shape(f"rm -rf {shared}/tmp.*") == guard.SHARED_TEMP_SHAPE
    assert _shape(f"rm -rf {scratch}/*") == guard.SHARED_TEMP_SHAPE
    assert _shape("rm -rf *", cwd=str(shared)) == guard.SHARED_TEMP_SHAPE


def test_shared_root_and_its_parent_are_refused(roots):
    shared, scratch = roots
    assert _shape(f"rm -rf {shared}") == guard.SHARED_TEMP_SHAPE
    assert _shape(f"rm -r {scratch}/") == guard.SHARED_TEMP_SHAPE
    assert _shape(f"rm -rf {shared.parent}") == guard.SHARED_TEMP_SHAPE


def test_session_scratch_dir_and_named_paths_pass(roots):
    shared, scratch = roots
    session_dir = scratch / "1" / "sessions" / "sess-a"
    assert _shape(f"rm -rf {session_dir}") is None
    assert _shape(f"rm -rf {session_dir}/runs/*") is None
    assert _shape(f"rm -rf {shared}/tmp.AbC123") is None


def test_non_recursive_and_force_only_rm_are_ignored(roots):
    shared, _ = roots
    assert _shape(f"rm -f {shared}/tmp.*") is None
    assert _shape(f"rm --force {shared}/tmp.*") is None
    assert _shape('rm "$T"') is None


def test_wrapped_and_chained_rm_is_checked(roots):
    shared, _ = roots
    assert _shape(f"cd /x && sudo rm -Rf {shared}/*") == guard.SHARED_TEMP_SHAPE
    assert _shape(f"echo ok\nrm --recursive {shared}/a*") == guard.SHARED_TEMP_SHAPE


def test_reason_names_shape_targets_and_recovery():
    reason = format_recursive_rm_reason(
        guard.UNRESOLVED_SHAPE, ["$(dirname $(mktemp -u))/tmp.*"], False
    )
    assert "$(dirname $(mktemp -u))/tmp.*" in reason
    assert "trap 'rm -rf \"$T\"' EXIT" in reason
    assert "shell-and-cli.md" in reason
    assert "lint-destructive-git" in reason


def _payload(command: str, cwd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


def test_engine_guard_denies_incident(roots):
    reason, outcome = engine.evaluate_payload(_payload(INCIDENT, "/"))
    assert outcome == "denied"
    assert "recursive delete" in reason


def test_engine_guard_passes_creating_call_cleanup(roots, monkeypatch):
    monkeypatch.setattr(engine, "_claimed_worktree_threats", lambda targets: [])
    command = 'T=$(mktemp -d); trap \'rm -rf "$T"\' EXIT; rm -rf "$T"'
    assert engine.evaluate_payload(_payload(command, "/")) is None


def test_client_guard_denies_shared_temp_glob(roots):
    shared, _ = roots
    command = f"rm -rf {shared}/tmp.*"
    result = local_policies.lint_destructive_git(
        _payload(command, "/"), parse_shell(command)
    )
    assert result.outcome == local_policies.DENY
    assert "shared temp root" in result.message
