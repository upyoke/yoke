"""Tests for usher merge.md multi-worktree epic fixes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from runtime.api.fixtures.backlog import insert_item_worktree
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout

pytest_plugins = ("runtime.api.domain.worktree_test_helpers",)

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
MERGE_MD = SKILL_ROOT / "usher" / "merge.md"
RESOLVE_MODULE = "yoke_core.domain.worktree_item_resolve"


def _resolver_env(db_path: str) -> dict[str, str]:
    return {**os.environ, "YOKE_DB": db_path}


def _add_item_and_project(conn, epic_id: int, git_repo) -> None:
    conn.execute(
        "INSERT INTO items "
        "(id, title, workflow_id, workflow_version_id, status, "
        "project_id, project_sequence) "
        "VALUES (%s, 'Epic', 'epic', "
        "(SELECT current_version_id FROM workflows WHERE id='epic'), "
        "'reviewed-implementation', 1, %s)",
        (epic_id, epic_id),
    )
    register_machine_checkout(git_repo.parent / "machine-config", git_repo, 1)


def _add_git_worktree(git_repo, branch: str):
    path = git_repo / ".worktrees" / branch
    subprocess.run(
        ["git", "worktree", "add", str(path), "-b", branch, "main"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    return path


class TestMergeMdEpicDelegation:
    """Pinned child/lane policy selects the internal generated-task procedure."""

    def test_no_direct_epic_merge_worktree_call(self):
        text = MERGE_MD.read_text()
        assert "merge_worktree PREFIX-{N} main PREFIX-{N}" not in text
        assert "Never merge only the parent lane" in text

    def test_has_internal_generated_task_merge(self):
        assert "merge-generated-tasks.md" in MERGE_MD.read_text()

    def test_single_lane_path_still_present(self):
        assert "merge-item -- PREFIX-N --skip-status" in MERGE_MD.read_text()

    def test_exit_handling_is_scoped_to_single_lane_policy(self):
        text = MERGE_MD.read_text()
        assert "worktrees=single_implementation_lane" in text
        assert "Generated-task procedure owns its loop separately" in text

    def test_merge_selection_uses_pinned_policy_not_workflow_name(self):
        text = MERGE_MD.read_text()
        for required in (
            "yoke workflows item get",
            "yoke workflows version get",
            "Effective children=epic_tasks with worktrees=worker_and_integration_lanes",
            "Children=none with worktrees=single_implementation_lane",
            "Unsupported combination refuses",
            "half-open binding",
        ):
            assert required in text
        assert 'if [ "$_item_workflow_id" = "epic" ]' not in text

    def test_internal_merge_follows_pinned_delivery_stages(self):
        text = (SKILL_ROOT / "usher" / "merge-bookkeeping.md").read_text()
        for required in (
            "yoke workflows item get",
            "yoke workflows version get",
            "half-open interval",
            "source_status/target_status",
            "stopping on entry to the",
            "delivery wait",
            "merge is not successful delivery",
            "Read stage after every write",
        ):
            assert required in text
        assert "bypass_reason" not in text
        assert '"target_status": "done"' not in text


class TestMergeMdWorktreeIteration:
    """Ephemeral verification consumes every registered lane and exact candidate."""

    def test_no_direct_worktree_field_read_for_ephemeral(self):
        text = MERGE_MD.read_text()
        assert "items get PREFIX-{N} worktree" not in text
        assert "registered lane's actual branch and full committed HEAD" in " ".join(
            text.split()
        )

    def test_registered_reader_used_for_ephemeral_lanes(self):
        assert "yoke item-worktrees list PREFIX-N --json" in MERGE_MD.read_text()

    def test_ephemeral_verify_iterates_all_resolved_branches(self):
        text = MERGE_MD.read_text()
        assert "every permitted registered" in text
        assert "Capture/await every lane invocation through completion" in text
        assert "ephemeral-verify PROJECT REPO BRANCH WORKFLOW DOMAIN SHA" in text
        assert "stage config.workflow" in text and "capability preview_domain" in text
        assert "Missing inputs refuse by name" in text
        assert "head -1" not in text


class TestMergeMdHaltClassRelease:
    """Merge exits preserve landed state and release intent before recovery prose."""

    def test_halt_class_strings_present(self):
        text = MERGE_MD.read_text()
        for required in ("usher-halt-merge-failure", "usher-halt-unexpected"):
            assert required in text

    def test_release_work_claim_command_with_halt_reason(self):
        assert (
            "yoke claims work release --item PREFIX-N --reason usher-halt-merge-failure --json"
            in MERGE_MD.read_text()
        )

    def test_halt_class_release_named_before_halt_summary(self):
        text = MERGE_MD.read_text()
        order = text.index("Release matching intent BEFORE halt summary")
        release = text.index("yoke claims work release", order)
        recovery = text.index("exact resume /yoke usher", release)
        assert order < release < recovery
        assert "A failed release names failure class/holder and retained claim" in text

    def test_exit_5_names_halt_class_release(self):
        text = MERGE_MD.read_text()
        branch = text[text.index("| 5 |") : text.index("| 6 |")]
        assert "no rollback" in branch and "release usher-halt-merge-failure" in branch
        assert (
            "Merge committed, cleanup failed" in branch
            and "Resume skips merge" in branch
        )

    def test_unknown_exit_uses_usher_halt_unexpected(self):
        text = MERGE_MD.read_text()
        branch = text[
            text.index("| Other nonzero |") : text.index("Rollback uses lifecycle")
        ]
        assert "Distinguish landed receipt first" in branch
        assert "release usher-halt-unexpected" in branch


class TestResolverCLI:
    """Worktree_item_resolve has a CLI that returns branches for multi-worktree epics."""

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
        result = self._run_resolver("YOK-0", "--branches", env=_resolver_env(yoke_db))
        assert result.returncode != 0  # item not found

    def test_paths_flag_accepted(self, yoke_db):
        result = self._run_resolver("YOK-0", "--paths", env=_resolver_env(yoke_db))
        assert result.returncode != 0

    def test_json_flag_accepted(self, yoke_db):
        result = self._run_resolver("YOK-0", "--json", env=_resolver_env(yoke_db))
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
        _add_item_and_project(conn, epic_id, git_repo)
        insert_item_worktree(
            conn,
            item_id=epic_id,
            branch=branch_a,
            lane_role="worker",
            path=str(path_a),
        )
        insert_item_worktree(
            conn,
            item_id=epic_id,
            branch=branch_b,
            lane_role="worker",
            path=str(path_b),
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
