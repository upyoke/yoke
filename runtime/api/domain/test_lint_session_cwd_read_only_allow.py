"""Integration test for the read-only / self-orientation allow branch.

Covers AC-1 + AC-3: a read-only db_router query invoked from a cwd
outside the session's claim allows (and emits the new allow event),
while a non-read-only command from the same cwd still denies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_claimed_worktree(conn, repo):
    register_machine_checkout(
        Path(repo).parent / "machine-config",
        Path(repo),
        1,
    )
    seed_item(conn, item_id=1691, branch="YOK-1691")
    seed_item_claim(conn, "sid-1", item_id=1691)
    (repo / ".worktrees" / "YOK-1691").mkdir(parents=True)


# ---------------------------------------------------------------------------
# Read-only db_router query from outside-authority cwd allows
# ---------------------------------------------------------------------------


class TestReadOnlySignatureAllowsFromOutsideCwd:
    def test_db_router_query_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": "/opt/elsewhere",
            "tool_input": {
                "command": (
                    'python3 -m yoke_core.cli.db_router '
                    'query "SELECT 1"'
                ),
            },
        })

        assert verdict.allow is True

    def test_who_claims_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": "/opt/elsewhere",
            "tool_input": {
                "command": (
                    "python3 -m runtime.harness.harness_sessions "
                    "who-claims YOK-1691"
                ),
            },
        })

        assert verdict.allow is True

    def test_git_status_allows_from_outside_authority(self, conn, repo):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": "/opt/elsewhere",
            "tool_input": {"command": "git status"},
        })

        assert verdict.allow is True


# ---------------------------------------------------------------------------
# AC-1 continued: emit the new allow event, not the deny event
# ---------------------------------------------------------------------------


class TestReadOnlyAllowEmitsCorrectEvent:
    def test_allowed_signature_calls_allow_emitter_only(
        self, conn, monkeypatch, repo,
    ):
        _seed_claimed_worktree(conn, repo)

        allow_calls: list[dict] = []
        deny_calls: list[dict] = []

        def _allow(session_id, read_only_signature, claim_count):
            allow_calls.append({
                "session_id": session_id,
                "read_only_signature": read_only_signature,
                "claim_count": claim_count,
            })

        def _deny(session_id, offending_target, claim_count):
            deny_calls.append({
                "session_id": session_id,
                "offending_target": offending_target,
                "claim_count": claim_count,
            })

        monkeypatch.setattr(
            lint_session_cwd, "emit_mismatch_allowed_read_only", _allow,
        )
        monkeypatch.setattr(
            lint_session_cwd, "emit_mismatch_denied", _deny,
        )

        from runtime.harness.hook_runner.types import HookContext, Outcome

        record = HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude",
            payload={
                "session_id": "sid-1",
                "cwd": "/opt/elsewhere",
                "tool_input": {
                    "command": (
                        'python3 -m yoke_core.cli.db_router '
                        'query "SELECT 1"'
                    ),
                },
            },
            tool_name="Bash", cwd="/opt/elsewhere", session_id="sid-1",
        )

        decision = lint_session_cwd.evaluate(record)

        assert decision.outcome is Outcome.NOOP
        # No deny emission.
        assert deny_calls == []
        # One allow emission carrying the matched signature label.
        assert len(allow_calls) == 1
        assert allow_calls[0]["read_only_signature"] == "db_router-query"


# ---------------------------------------------------------------------------
# A non-read-only command from the same outside cwd still denies
# ---------------------------------------------------------------------------


class TestNonReadOnlyStillDenies:
    def test_mutating_command_from_outside_authority_denies(
        self, conn, repo,
    ):
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": "/opt/elsewhere",
            "tool_input": {
                "command": (
                    "python3 -m yoke_core.engines.advance_implementation_entry "
                    "--item YOK-1691"
                ),
            },
        })

        assert verdict.allow is False

    def test_synthetic_outside_path_still_denies(self, conn, repo):
        # AC-3 cwd-outside-authority regression: command names an
        # absolute target outside the free-path allowlist and outside
        # any claimed worktree. ``/opt/elsewhere`` is used (mirroring
        # ``test_target_outside_authority_denies``) because pytest's
        # ``tmp_path`` lives under ``/var/folders`` which the lint's
        # free-path rule authorizes regardless of claim.
        _seed_claimed_worktree(conn, repo)

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-1",
            "cwd": str(repo),
            "tool_input": {"command": "touch /opt/elsewhere/out.py"},
        })

        assert verdict.allow is False
        assert verdict.offending_target == "/opt/elsewhere/out.py"
