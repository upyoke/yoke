"""Evidence-based regressions for legitimate commands refused by hook lints.

The cases mirror the collected denial ledger: search/process diagnostics,
exact-path git recovery, test-fixture SQL, in-memory migration rehearsals,
lane-source rendering, read-only import probes, and temporary-file cleanup.
Each false positive sits beside a true positive for the guarded command class.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from yoke_core.domain import lint_destructive_git as destructive_git
from yoke_core.domain import lint_no_agent_runtime_api_import_from_c as import_guard
from yoke_core.domain import lint_pipe_to_truncator as pipe_guard
from yoke_core.domain.lint_db_cmd_test_helpers import _assert_allows, _assert_blocks
from yoke_core.domain.lint_shell_quoted_function_payload_messages import (
    build_choreography_remediation,
)


def _payload(command: str, **extra: object) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "incident-regression",
        **extra,
    }


@pytest.mark.parametrize(
    "command",
    [
        "grep -n pytest runtime/api/conftest.py | head -30",
        "ps aux | rg 'pytest|watch_pytest|qa case' | head -20",
        "ps -axo pid,command | sort -k1 | head -20",
        "rg -n 'pytest|watch_pytest' runtime/api | head -40",
        "rg 'yoke watch merge --' packages runtime | head",
        "grep -R -n pytest runtime/api | head -30",
        "find . -name '*.py' | head -20",
        (
            "yoke ouroboros field-note append --kind observation "
            "--evidence 'blocked pytest runtime/api/ -q | head -30'"
        ),
        (
            "yoke ouroboros field-note append --kind observation "
            "--evidence \"python3 -m yoke_core.tools.watch_pytest -- x | tail -8\""
        ),
    ],
)
def test_narrow_search_and_process_filters_are_not_live_long_commands(command: str) -> None:
    with mock.patch.object(pipe_guard, "_read_mode", return_value="deny"):
        assert pipe_guard.evaluate_payload(_payload(command)) is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest runtime/api -q | head -20",
        "python3 -m yoke_core.tools.watch_pytest -- runtime/api -q | tail -40",
        "yoke watch merge YOK-1 | head -20",
    ],
)
def test_live_long_commands_still_refuse_truncating_pipes(command: str) -> None:
    with mock.patch.object(pipe_guard, "_read_mode", return_value="deny"):
        assert pipe_guard.evaluate_payload(_payload(command)) is not None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=False, env=env, timeout=10,
    )


def test_exact_path_restore_names_patch_level_recovery_and_only_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    for name in ("generated-a.md", "generated-b.md", "owned-change.md"):
        (repo / name).write_text("before\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    for name in ("generated-a.md", "generated-b.md", "owned-change.md"):
        (repo / name).write_text("after\n", encoding="utf-8")

    command = f"git -C {repo} restore -- generated-a.md generated-b.md"
    with mock.patch.object(destructive_git, "_read_mode", return_value="deny"), \
         mock.patch.object(destructive_git, "_claimed_worktree_threats", return_value=[]):
        verdict = destructive_git.evaluate_payload(_payload(command))

    assert verdict is not None
    reason = verdict[1]
    assert "apply_patch" in reason
    assert "git diff -- <path>" in reason
    assert "generated-a.md" in reason and "generated-b.md" in reason
    assert "owned-change.md" not in reason


def test_destructive_git_denial_names_the_config_file(tmp_path: Path) -> None:
    note = f"Policy source: {tmp_path}/.yoke/lint-config (lint_destructive_git=deny)."
    with mock.patch.object(destructive_git, "_config_note", return_value=note), \
         mock.patch.object(destructive_git, "_read_mode", return_value="deny"), \
         mock.patch.object(destructive_git, "_is_git_repo", return_value=True), \
         mock.patch.object(destructive_git, "_check_threat", return_value=["a.txt"]):
        verdict = destructive_git.evaluate_payload(_payload("git reset --hard"))
    assert verdict is not None
    assert note in verdict[1]


def test_test_fixture_authoring_with_lifecycle_sql_is_allowed() -> None:
    _assert_allows(
        "python3 -c 'from pathlib import Path; "
        'Path("/tmp/test_fixture.py").write_text("INSERT INTO items VALUES (1)")\''
    )


def test_in_memory_sqlite_lifecycle_rehearsal_is_allowed() -> None:
    _assert_allows(
        "python3 -c 'import sqlite3; c=sqlite3.connect(\":memory:\"); "
        'c.execute("CREATE TABLE items(id INTEGER)"); '
        'c.execute("INSERT INTO items VALUES (1)")\''
    )


def test_file_backed_inline_lifecycle_mutation_still_blocks() -> None:
    decision = _assert_blocks(
        "python3 -c 'import sqlite3; c=sqlite3.connect(\"/tmp/authority.db\"); "
        'c.execute("INSERT INTO items VALUES (1)")\''
    )
    assert "lifecycle-owned table" in decision["permissionDecisionReason"]


@pytest.mark.parametrize(
    "command",
    [
        'python3 -c "from yoke_core.domain.recipe_event_extractor import '
        'extract_recipe_events; print(extract_recipe_events())"',
        'python3 -c "from yoke_core.domain.event_registry import '
        'discover_event_names, PURGED_EVENT_NAMES; '
        'print(sorted(discover_event_names() - PURGED_EVENT_NAMES))"',
    ],
)
def test_read_only_import_inspection_probes_are_allowed(command: str) -> None:
    with mock.patch.object(import_guard, "_read_mode", return_value="deny"):
        assert import_guard.evaluate_payload(_payload(command)) is None


def test_dispatch_import_probe_still_blocks() -> None:
    command = (
        'python3 -c "from yoke_core.domain.yoke_function_dispatch import dispatch; '
        'dispatch(request)"'
    )
    with mock.patch.object(import_guard, "_read_mode", return_value="deny"):
        assert import_guard.evaluate_payload(_payload(command)) is not None


def test_renderer_denial_names_a_lane_source_command_that_targets_the_worktree() -> None:
    reason = build_choreography_remediation(
        "yoke_core.domain.agents_render render", "agents.render.run"
    )
    assert "yoke dev run -- yoke agents render" in reason
    assert "render --target-root ." in reason


def test_explicit_temp_capture_cleanup_is_not_destructive_git() -> None:
    command = "rm -f /tmp/yoke-validation-capture.log"
    with mock.patch.object(destructive_git, "_read_mode", return_value="deny"):
        assert destructive_git.evaluate_payload(_payload(command, cwd="/tmp")) is None
