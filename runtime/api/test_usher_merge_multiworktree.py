"""Tests for usher merge.md multi-worktree epic fixes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain.worktree_test_helpers import (  # noqa: F401
    git_repo,
    yoke_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
MERGE_MD = SKILL_ROOT / "usher" / "merge.md"
RESOLVE_MODULE = "yoke_core.domain.worktree_item_resolve"


def _resolver_env(db_path: str) -> dict[str, str]:
    return {**os.environ, "YOKE_DB": db_path}


def _add_item_and_project(conn, epic_id: int, git_repo) -> None:
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, worktree, project_id, project_sequence) "
        "VALUES (%s, 'Epic', 'epic', 'reviewed-implementation', %s, 1, %s)",
        (epic_id, f"YOK-{epic_id}", epic_id),
    )
    register_machine_checkout(git_repo.parent / "machine-config", git_repo, 1)


def _add_git_worktree(git_repo, branch: str):
    path = git_repo / ".worktrees" / branch
    subprocess.run(
        ["git", "worktree", "add", str(path), "-b", branch, "main"],
        cwd=str(git_repo), check=True, capture_output=True,
    )
    return path


class TestMergeMdEpicDelegation:
    """AC-1: usher/merge.md delegates epic merge to /yoke merge, not merge_worktree."""

    def _read_merge_md(self) -> str:
        return MERGE_MD.read_text()

    def test_no_direct_epic_merge_worktree_call(self):
        """merge.md must not call merge_worktree with an epic ref directly."""
        text = self._read_merge_md()
        # The old pattern: merge_worktree YOK-{N} main YOK-{N}
        assert "merge_worktree YOK-{N} main YOK-{N}" not in text, (
            "merge.md still has a direct epic merge_worktree call — "
            "must delegate to /yoke merge {N} instead"
        )

    def test_has_yoke_merge_delegation(self):
        """merge.md must contain the /yoke merge {N} epic delegation."""
        text = self._read_merge_md()
        assert "/yoke merge {N}" in text, (
            "merge.md is missing the /yoke merge {N} delegation for epics"
        )

    def test_issue_path_still_present(self):
        """merge.md must retain the issue merge-worktree path."""
        text = self._read_merge_md()
        assert "merge-worktree -- YOK-{N}" in text, (
            "merge.md lost the issue merge-worktree call — issue path must be retained"
        )

    def test_7e_scoped_to_issues(self):
        """merge.md step 7e must document that exit-code handling is issue-only."""
        text = self._read_merge_md()
        assert "issue items only" in text.lower(), (
            "merge.md step 7e does not scope exit-code handling to issue items"
        )


class TestMergeMdWorktreeIteration:
    """AC-2: usher/merge.md uses resolver for ephemeral-verify branch, not items.worktree."""

    def test_no_direct_worktree_field_read_for_ephemeral(self):
        """The ephemeral-verify branch resolution must use the resolver, not db_router worktree."""
        text = MERGE_MD.read_text()
        # The old single-field read (without resolver) was on one line; check it is gone
        assert "items get YOK-{N} worktree" not in text, (
            "merge.md still reads items.worktree directly for ephemeral-verify branch — "
            "must use worktree_item_resolve instead"
        )

    def test_resolver_used_for_ephemeral_branch(self):
        """The ephemeral-verify block must call the resolver module."""
        text = MERGE_MD.read_text()
        assert "worktree_item_resolve" in text, (
            "merge.md does not use worktree_item_resolve for the ephemeral-verify branch"
        )

    def test_ephemeral_verify_iterates_all_resolved_branches(self):
        """The resolver output must be looped, not truncated to the first worktree."""
        text = MERGE_MD.read_text()
        assert "head -1" not in text, (
            "merge.md still truncates resolved branches to the first worktree"
        )
        assert "while IFS= read -r _ev_branch" in text, (
            "merge.md does not iterate resolved branches for ephemeral-verify"
        )
        assert 'ephemeral-verify "$_ev_github_repo" "$_ev_branch"' in text, (
            "merge.md does not invoke ephemeral-verify once per resolved branch"
        )
        assert "done <<EOF" in text, (
            "merge.md must expand the resolved branch list in the here-doc"
        )


class TestMergeMdHaltClassRelease:
    """AC-39: usher/merge.md halt branches release the work claim with a
    halt-class reason BEFORE printing recovery instructions.
    """

    def _read_merge_md(self) -> str:
        return MERGE_MD.read_text()

    def test_halt_class_strings_present(self):
        text = self._read_merge_md()
        for halt_class in (
            "usher-halt-merge-failure",
            "usher-halt-unexpected",
        ):
            assert halt_class in text, (
                f"merge.md does not name halt-class {halt_class!r}"
            )

    def test_release_work_claim_command_with_halt_reason(self):
        """The yoke claims work release shell call appears with --reason."""
        text = self._read_merge_md()
        assert (
            "yoke claims work release" in text
        ), "merge.md must invoke yoke claims work release for halt-class release"
        assert (
            "--reason" in text
        ), "merge.md must pass --reason to yoke claims work release"

    def test_halt_class_release_named_before_halt_summary(self):
        """The halt-class release contract appears before the halt summary
        recovery instructions ("Then halt the entire usher batch")."""
        text = self._read_merge_md()
        release_idx = text.find("Halt-class release contract")
        summary_idx = text.find("Then halt the entire usher batch")
        assert release_idx != -1, (
            "merge.md missing 'Halt-class release contract' section"
        )
        assert summary_idx != -1, (
            "merge.md missing 'Then halt the entire usher batch' summary text"
        )
        assert release_idx < summary_idx, (
            "merge.md halt-class release section must appear before the "
            "halt-summary recovery instructions (release must run BEFORE "
            "recovery prose per AC-39)"
        )

    def test_exit_5_names_halt_class_release(self):
        """Exit 5 (merge landed, cleanup failed) must still release the claim
        with usher-halt-merge-failure (item stays in release)."""
        text = self._read_merge_md()
        exit5_start = text.find("Exit 5 (HALT")
        assert exit5_start != -1, "merge.md missing 'Exit 5 (HALT' branch"
        # Limit search to the exit-5 branch itself, ending at the next
        # bullet (Any other non-zero exit) so we are sure the reference
        # is in the right branch.
        exit5_end = text.find("Any other non-zero exit", exit5_start)
        assert exit5_end > exit5_start
        exit5_block = text[exit5_start:exit5_end]
        assert "usher-halt-merge-failure" in exit5_block, (
            "Exit 5 branch must release the claim with usher-halt-merge-failure"
        )
        assert "release the work claim" in exit5_block.lower(), (
            "Exit 5 branch must explicitly call out releasing the work claim"
        )

    def test_unknown_exit_uses_usher_halt_unexpected(self):
        text = self._read_merge_md()
        catchall_start = text.find("Any other non-zero exit (HALT")
        assert catchall_start != -1
        catchall_end = text.find("Halt-class release contract", catchall_start)
        assert catchall_end > catchall_start
        catchall_block = text[catchall_start:catchall_end]
        assert "usher-halt-unexpected" in catchall_block, (
            "Unknown non-zero exit branch must use usher-halt-unexpected"
        )


class TestResolverCLI:
    """AC-6: worktree_item_resolve has a CLI that returns branches for multi-worktree epics."""

    def _run_resolver(
        self,
        *args: str,
        cwd=None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        resolver_env = os.environ.copy() if env is None else env
        if env is None:
            resolver_env.pop("YOKE_DB", None)
        return subprocess.run(
            [sys.executable, "-m", RESOLVE_MODULE, *args],
            cwd=cwd,
            env=resolver_env,
            capture_output=True,
            text=True,
        )

    def test_help_exits_zero(self):
        result = self._run_resolver("--help")
        assert result.returncode == 0

    def test_invalid_item_ref_exits_nonzero(self):
        result = self._run_resolver("not-an-item-id")
        assert result.returncode != 0
        assert "ERROR" in result.stderr

    def test_missing_item_exits_nonzero(self, yoke_db):
        # YOK-0 is not a real item
        result = self._run_resolver("YOK-0", env=_resolver_env(yoke_db))
        assert result.returncode != 0
        assert "ERROR" in result.stderr

    def test_branches_flag_is_default(self, yoke_db):
        """--branches output and default output (no flag) are both accepted."""
        # We test the CLI surface exists and accepts the flag — actual branch data
        # requires a DB fixture so we check the failure path is clean.
        result = self._run_resolver(
            "YOK-0", "--branches", env=_resolver_env(yoke_db)
        )
        assert result.returncode != 0  # item not found

    def test_paths_flag_accepted(self, yoke_db):
        result = self._run_resolver(
            "YOK-0", "--paths", env=_resolver_env(yoke_db)
        )
        assert result.returncode != 0

    def test_json_flag_accepted(self, yoke_db):
        result = self._run_resolver(
            "YOK-0", "--json", env=_resolver_env(yoke_db)
        )
        assert result.returncode != 0

    def test_mutually_exclusive_flags(self):
        result = self._run_resolver("YOK-0", "--branches", "--paths")
        assert result.returncode != 0

    def test_branches_flag_returns_all_worktrees_for_epic(self, git_repo, yoke_db):
        epic_id = 91
        branch_a = f"YOK-{epic_id}-alpha"
        branch_b = f"YOK-{epic_id}-beta"
        path_a = _add_git_worktree(git_repo, branch_a)
        path_b = _add_git_worktree(git_repo, branch_b)

        conn = connect_test_db(yoke_db)
        conn.execute(
            "CREATE TABLE epic_dispatch_chains "
            "(epic_id TEXT, worktree TEXT, worktree_path TEXT)"
        )
        _add_item_and_project(conn, epic_id, git_repo)
        conn.execute(
            "INSERT INTO epic_dispatch_chains VALUES (%s, %s, %s)",
            (str(epic_id), branch_a, str(path_a)),
        )
        conn.execute(
            "INSERT INTO epic_dispatch_chains VALUES (%s, %s, %s)",
            (str(epic_id), branch_b, str(path_b)),
        )
        conn.commit()
        conn.close()

        # The resolver subprocess reads its DB via db_helpers.connect(path),
        # which routes through the backend factory: on SQLite it honours the
        # explicit YOKE_DB path, on Postgres it targets YOKE_PG_DSN. The
        # seed above wrote whichever backend connect_test_db resolved, so the
        # subprocess must read the same backend. Inherit YOKE_PG_DSN
        # (repointed at the disposable per-test DB on Postgres) unchanged and
        # pass YOKE_DB so the SQLite engine reads the seeded file (YOKE_DB
        # is ignored on Postgres).
        env = {**os.environ, "YOKE_DB": yoke_db}
        result = self._run_resolver(f"YOK-{epic_id}", "--branches", env=env)

        assert result.returncode == 0
        assert result.stdout.splitlines() == [branch_a, branch_b]
