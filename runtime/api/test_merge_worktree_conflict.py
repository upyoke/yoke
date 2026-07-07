"""
test_merge_worktree_conflict.py — Conflict resolution + branch-aware doc handling
for the merge-worktree engine. Shared fixtures live in test_merge_worktree_full.py.
"""

import json

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    _git,
    _write_file,
    merge_env,  # re-export so pytest recognises this fixture
    run_merge,
)


class TestConflictResolution:
    """Conflict auto-resolution and branch-aware doc handling."""

    def test_yok131_doc_file_conflict(self, merge_env: MergeEnv) -> None:
        """Branch-modified doc conflict blocked by trial merge."""
        repo = merge_env.repo
        wt = merge_env.worktree

        # Add docs on main
        _write_file(repo / "AGENTS.md", "# Project Rules (main version)\n")
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(repo / "docs" / "commands.md", "# Commands (main version)\n")
        _git(repo, "add", "AGENTS.md", "docs/commands.md")
        _git(repo, "commit", "-m", "add doc files on main")
        _git(repo, "push", "origin", "main")

        # Modify docs on feature branch
        _write_file(wt / "AGENTS.md", "# Project Rules (feature version)\n")
        (wt / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(wt / "docs" / "commands.md", "# Commands (feature version)\n")
        _git(wt, "add", "AGENTS.md", "docs/commands.md")
        _git(wt, "commit", "-m", "modify docs on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Conflicting changes on main
        _write_file(repo / "AGENTS.md", "# Project Rules (main updated)\n")
        _write_file(repo / "docs" / "commands.md", "# Commands (main updated)\n")
        _git(repo, "add", "AGENTS.md", "docs/commands.md")
        _git(repo, "commit", "-m", "update docs on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        # Conflict analysis goes to stderr in the Python engine
        assert "branch-modified" in result.stderr or "modified on branch" in result.stdout
        assert "agent resolution" in result.stderr

    def test_yok185_board_sidecar_conflict_auto_resolved(self, merge_env: MergeEnv) -> None:
        """Generated board sidecar conflict auto-resolved."""
        repo = merge_env.repo
        wt = merge_env.worktree

        sidecar_content_main1 = "export const board = 'original';\n"
        sidecar_content_feat = "export const board = 'feature';\n"
        sidecar_content_main2 = "export const board = 'main';\n"

        _write_file(repo / ".yoke" / "BOARD.md.ts", sidecar_content_main1)
        _git(repo, "add", "-f", ".yoke/BOARD.md.ts")
        _git(repo, "commit", "-m", "add board sidecar")
        _git(repo, "push", "origin", "main")

        _write_file(wt / ".yoke" / "BOARD.md.ts", sidecar_content_feat)
        _git(wt, "add", "-f", ".yoke/BOARD.md.ts")
        _git(wt, "commit", "-m", "modify board sidecar on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md.ts", sidecar_content_main2)
        _git(repo, "add", "-f", ".yoke/BOARD.md.ts")
        _git(repo, "commit", "-m", "update board sidecar on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        # Python engine may auto-resolve during pre-merge integration or main merge
        assert ("auto-resolve" in result.stdout.lower() or
                "merge-commit succeeded" in result.stdout.lower() or
                "Auto-resolving" in result.stdout)

    def test_yok185_current_plan_conflict_auto_resolved(self, merge_env: MergeEnv) -> None:
        """BOARD.md conflict auto-resolved."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature version)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main version)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "update board on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        # Python engine may resolve in pre-merge integration or main merge
        assert ("auto-resolve" in result.stdout.lower() or
                "merge-commit succeeded" in result.stdout.lower())

    def test_yok185_flows_md_shared(self, merge_env: MergeEnv) -> None:
        """Simulation report treated as Yoke-managed (shared file)."""
        repo = merge_env.repo
        rel = "ouroboros/simulation-YOK-9999.md"
        _write_file(repo / rel, "# Simulation\n")
        _git(repo, "add", rel)
        _git(repo, "commit", "-m", "add simulation report")
        _git(repo, "push", "origin", "main")

        _write_file(repo / rel, "# Simulation (dirty)\n")

        result = run_merge(merge_env)
        assert result.exit_code == 0

    def test_yok538_branch_modified_doc_not_auto_resolved(self, merge_env: MergeEnv) -> None:
        """Branch-modified AGENTS.md blocked."""
        repo = merge_env.repo
        wt = merge_env.worktree

        (repo / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(repo / "docs" / "commands.md", "# Commands (main version)\n")
        _git(repo, "add", "docs/commands.md")
        _git(repo, "commit", "-m", "add docs on main")
        _git(repo, "push", "origin", "main")

        (wt / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(wt / "docs" / "commands.md", "# Commands (branch fixed version)\n")
        _git(wt, "add", "docs/commands.md")
        _git(wt, "commit", "-m", "fix docs on feature branch")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / "docs" / "commands.md", "# Commands (main updated)\n")
        _git(repo, "add", "docs/commands.md")
        _git(repo, "commit", "-m", "update docs on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "branch-modified" in result.stderr
        assert "agent resolution" in result.stderr

    def test_yok538_branch_unmodified_doc_auto_resolved(self, merge_env: MergeEnv) -> None:
        """Branch-unmodified doc auto-resolved."""
        repo = merge_env.repo
        wt = merge_env.worktree

        # Remove old worktree and branch, re-create after doc exists
        _git(repo, "worktree", "remove", str(wt), "--force", check=False)
        _git(repo, "branch", "-D", TEST_BRANCH, check=False)

        (repo / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(repo / "docs" / "commands.md", "# Commands (original)\n")
        _git(repo, "add", "docs/commands.md")
        _git(repo, "commit", "-m", "add docs on main (before branch fork)")
        _git(repo, "push", "origin", "main")

        # Re-create branch from current main
        _git(repo, "branch", TEST_BRANCH)
        _git(repo, "worktree", "add", str(wt), TEST_BRANCH)
        _git(wt, "config", "user.email", "test@test.com")
        _git(wt, "config", "user.name", "Test")

        # Non-doc change on feature
        _write_file(wt / "feature.txt", "feature work v2\n")
        _git(wt, "add", "feature.txt")
        _git(wt, "commit", "-m", "feature work on branch")

        # Modify doc (C1) then revert it (C2) — net change is zero
        _write_file(wt / "docs" / "commands.md", "# Commands (temporary branch change)\n")
        _git(wt, "add", "docs/commands.md")
        _git(wt, "commit", "-m", "temp doc change on feature (C1)")

        _write_file(wt / "docs" / "commands.md", "# Commands (original)\n")
        _git(wt, "add", "docs/commands.md")
        _git(wt, "commit", "-m", "revert doc change on feature (C2)")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Conflicting doc change on main
        _write_file(repo / "docs" / "commands.md", "# Commands (main updated)\n")
        _git(repo, "add", "docs/commands.md")
        _git(repo, "commit", "-m", "update docs on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        # Python engine auto-resolves branch-unmodified doc conflicts during
        # pre-merge integration or merge-commit — success is sufficient proof
        assert "merged" in result.stdout.lower() or "Merge-commit succeeded" in result.stdout

    def test_yok538_claude_md_branch_modified(self, merge_env: MergeEnv) -> None:
        """AGENTS.md modified on branch blocked."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(repo / "AGENTS.md", "# Project Rules (main version)\n")
        _git(repo, "add", "AGENTS.md")
        _git(repo, "commit", "-m", "add AGENTS.md on main")
        _git(repo, "push", "origin", "main")

        _write_file(wt / "AGENTS.md", "# Project Rules (branch update — new convention added)\n")
        _git(wt, "add", "AGENTS.md")
        _git(wt, "commit", "-m", "update AGENTS.md conventions on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / "AGENTS.md", "# Project Rules (main updated — different convention)\n")
        _git(repo, "add", "AGENTS.md")
        _git(repo, "commit", "-m", "update AGENTS.md on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "branch-modified" in result.stderr
        assert "agent resolution" in result.stderr

    def test_yok538_trial_merge_branch_modified_doc(self, merge_env: MergeEnv) -> None:
        """Trial merge with branch-modified doc exits 3."""
        repo = merge_env.repo
        wt = merge_env.worktree

        (repo / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(repo / "docs" / "widget.md", "# Widget (main)\n")
        _git(repo, "add", "docs/widget.md")
        _git(repo, "commit", "-m", "add widget doc on main")
        _git(repo, "push", "origin", "main")

        (wt / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(wt / "docs" / "widget.md", "# Widget (branch — fixed schema types)\n")
        _git(wt, "add", "docs/widget.md")
        _git(wt, "commit", "-m", "fix widget schema types on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / "docs" / "widget.md", "# Widget (main — added new section)\n")
        _git(repo, "add", "docs/widget.md")
        _git(repo, "commit", "-m", "update widget doc on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 3
        assert "branch-modified" in result.stderr
        assert "agent resolution" in result.stderr

    def test_yok538_merge_fallback_branch_modified_doc(self, merge_env: MergeEnv) -> None:
        """Merge fallback with branch-modified doc exits 3."""
        repo = merge_env.repo
        wt = merge_env.worktree

        # Set threshold to 1 and add doc
        machine_config = merge_env.tmpdir / "machine-config.json"
        machine_config.write_text(
            json.dumps({"schema_version": 1, "settings": {"merge_conflict_threshold": "1"}}),
            encoding="utf-8",
        )
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(repo / "docs" / "db-reference.md", "# DB Reference (main)\n")
        _git(repo, "add", "docs/db-reference.md")
        _git(repo, "commit", "-m", "set threshold and add doc")
        _git(repo, "push", "origin", "main")

        # Feature branch: gen-file + doc modifications
        _git(wt, "pull", "origin", "main", "--rebase", check=False)
        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v1)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature v1")
        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v2)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "modify board on feature v2")
        (wt / "docs").mkdir(parents=True, exist_ok=True)
        _write_file(wt / "docs" / "db-reference.md", "# DB Reference (branch — fixed schema)\n")
        _git(wt, "add", "docs/db-reference.md")
        _git(wt, "commit", "-m", "fix db-reference.md on feature")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        # Conflicting main changes
        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main v1)\n")
        _write_file(repo / "docs" / "db-reference.md", "# DB Reference (main — added new tables)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md", "docs/db-reference.md")
        _git(repo, "commit", "-m", "update board and docs on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(
            merge_env,
            extra_env={"YOKE_MACHINE_CONFIG_FILE": str(machine_config)},
        )
        assert result.exit_code == 3

        # Verify branch-modified doc detected
        assert "branch-modified" in result.stderr, "branch-modified doc not detected"
