"""Golden capture's remote path bypasses only local operand extraction."""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import seed_item, seed_item_claim
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    extract_command_targets,
)


REMOTE = "/Users/Shared/yoke-golden/test-home"
LOCAL = "/opt/unclaimed/capture.txt"
SUBJECT = "yoke test-machine golden-capture --project yoke"


@pytest.mark.parametrize(
    "command",
    [
        f"{SUBJECT} --destination {REMOTE}",
        f"{SUBJECT} --destination={REMOTE}",
        f"yoke --env prod test-machine golden-capture --project yoke --destination {REMOTE}",
        f"/usr/local/bin/yoke test-machine golden-capture --project yoke --destination {REMOTE}",
        f"{SUBJECT} --destination '$REMOTE_GOLDEN'",
    ],
)
def test_remote_destination_is_not_a_local_target(command):
    assert extract_command_targets(command) == []


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (f" > {LOCAL}", [LOCAL]),
        (f" 2>> {LOCAL}", [LOCAL]),
        (f" && touch {LOCAL}", [LOCAL]),
        (f" | tee {LOCAL}", [LOCAL]),
        (f" --probes-file {LOCAL}", [LOCAL]),
        (f" {LOCAL}", [LOCAL]),
    ],
)
def test_local_operands_still_extract(suffix, expected):
    assert (
        extract_command_targets(f"{SUBJECT} --destination {REMOTE}{suffix}") == expected
    )


@pytest.mark.parametrize(
    "command",
    [
        f"yoke test-machine verify --project yoke --destination {REMOTE}",
        f"other test-machine golden-capture --destination {REMOTE}",
    ],
)
def test_other_commands_keep_local_path_extraction(command):
    assert extract_command_targets(command) == [REMOTE]


@pytest.fixture
def worker(tmp_path):
    with test_database() as conn:
        repo = tmp_path / "repo"
        branch = "capture-worker"
        (repo / ".worktrees" / branch).mkdir(parents=True)
        register_machine_checkout(tmp_path / "machine-config", repo, 1)
        seed_item(conn, item_id=100, branch=branch, repo_path=repo)
        seed_item_claim(conn, "capture-worker-session", item_id=100)
        yield repo


@pytest.mark.parametrize("tool_name", ["Bash", "exec_command", "Shell"])
def test_claimed_worker_can_invoke_remote_capture(worker, tool_name):
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "capture-worker-session",
            "cwd": str(worker),
            "tool_name": tool_name,
            "tool_input": {"command": f"{SUBJECT} --destination {REMOTE}"},
        }
    )
    assert verdict.allow, verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        f"{SUBJECT} --destination {REMOTE} > {LOCAL}",
        f"{SUBJECT} --destination {REMOTE} && touch {LOCAL}",
        f"touch {LOCAL}",
    ],
)
def test_claimed_worker_still_cannot_write_unclaimed_local_path(worker, command):
    verdict = lint_session_cwd.evaluate_pre_tool_use(
        {
            "session_id": "capture-worker-session",
            "cwd": str(worker),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )
    assert not verdict.allow
    assert verdict.offending_target == LOCAL
