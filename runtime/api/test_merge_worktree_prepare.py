"""
test_merge_worktree_prepare.py — Preparation phase tests for the merge-worktree engine.

Covers: pre-flight checks, dirty file detection, branch validation,
simulation gate, and backlog/body diff visibility.

Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    _create_epic_tasks_db,
    _git,
    _insert_canonical_integration_simulation,
    _insert_plain_text_integration_simulation,
    _write_file,
    merge_env as _shared_merge_env,
    run_merge,
)
from yoke_core.engines.merge_boundary_ceremony import MERGE_CEREMONY_NONCE_ENV


@pytest.mark.parametrize(
    "first_module",
    ["merge_worktree_prepare_state", "merge_worktree_prepare"],
)
def test_prepare_modules_import_in_either_order(first_module: str) -> None:
    """Both public import surfaces initialize in a fresh interpreter."""
    other_module = (
        "merge_worktree_prepare"
        if first_module.endswith("_state")
        else "merge_worktree_prepare_state"
    )
    package = "yoke_core.engines"
    code = f"""
import importlib
importlib.import_module({f'{package}.{first_module}'!r})
importlib.import_module({f'{package}.{other_module}'!r})
prepare = importlib.import_module({f'{package}.merge_worktree_prepare'!r})
state = importlib.import_module({f'{package}.merge_worktree_prepare_state'!r})
assert all(hasattr(prepare, name) for name in ('MergeArgs', 'MergeContext', 'ConflictInfo', 'validate_args', 'resolve_context', 'preflight_checks', 'check_and_clean_root_dirty_state', 'prune_agent_worktrees', 'extract_generated_files', '_pre_merge_integration', '_stash_classify_gate', '_matches_glob'))
assert all(hasattr(state, name) for name in ('MergeContext', '_matches_glob', 'check_and_clean_root_dirty_state', 'prune_agent_worktrees', 'extract_generated_files', '_pre_merge_integration', '_stash_classify_gate'))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture(name="merge_env")
def _merge_env_fixture(tmp_path, request):
    """Expose the shared fixture without relying on plugin load order."""
    return _shared_merge_env.__wrapped__(tmp_path, request)


# ===========================================================================
# Tests: Dirty file handling
# ===========================================================================
class TestDirtyFileHandling:
    """Dirty file detection and safety stash."""

    def test_yok96_dirty_user_file(self, merge_env: MergeEnv) -> None:
        """Dirty user file in worktree exits 4."""
        _write_file(merge_env.worktree / "my-code.js", "uncommitted user work\n")
        result = run_merge(merge_env)
        assert result.exit_code == 4
        assert "Uncommitted non-Yoke files" in result.stderr

    def test_yok96_clean_worktree(self, merge_env: MergeEnv) -> None:
        """Clean worktree exits 0."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

    def test_yok96_safety_stash(self, merge_env: MergeEnv) -> None:
        """Dirty Yoke-managed report stashed/restored, no stale stash."""
        wt = merge_env.worktree
        rel = "ouroboros/simulation-YOK-9999.md"
        _write_file(wt / rel, "# simulation\n")
        _git(wt, "add", rel)
        _git(wt, "commit", "-m", "add simulation report")
        _git(wt, "push", "origin", TEST_BRANCH)
        # Now dirty it
        _write_file(wt / rel, "# simulation\ndirty report\n")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # No stale stash entries
        stash = _git(merge_env.repo, "stash", "list", check=False)
        assert "yoke-pre-rebase" not in stash.stdout


# ===========================================================================
# Tests: Body diff / gitignored files
# ===========================================================================
class TestBodyDiff:
    """Generated board files are gitignored, invisible to merge."""

    def test_body_diff_frontmatter_only(self, merge_env: MergeEnv) -> None:
        """Generated board sidecar is gitignored, do not affect merge."""
        _write_file(
            merge_env.repo / ".yoke" / "BOARD.md.ts",
            "---\nid: YOK-1\ntitle: Test item\nstatus: done\n---\nBody content.\n",
        )
        result = run_merge(merge_env)
        assert result.exit_code == 0

    def test_body_diff_body_change(self, merge_env: MergeEnv) -> None:
        """Generated board sidecar change invisible (gitignored)."""
        _write_file(
            merge_env.repo / ".yoke" / "BOARD.md.ts",
            "---\nid: YOK-1\ntitle: Test item\nstatus: done\n---\nModified body.\n",
        )
        result = run_merge(merge_env)
        assert result.exit_code == 0


# ===========================================================================
# Tests: Pre-flight checks
# ===========================================================================
class TestStandaloneBoundaryCeremony:
    """The command line reaches only half a standalone item's boundary."""

    def test_standalone_without_a_ceremony_nonce_never_merges(
        self, merge_env: MergeEnv,
    ) -> None:
        """The refusal fires before preflight, naming the real entrypoint."""
        result = run_merge(
            merge_env, extra_env={MERGE_CEREMONY_NONCE_ENV: ""},
        )
        assert result.exit_code == 1
        assert "missing merge-boundary ceremony nonce" in result.stderr
        assert "yoke merge item" in result.stderr
        assert "Running pre-flight checks" not in result.stdout


class TestPreflight:
    """Pre-flight validation."""

    def test_yok206_preflight_clean(self, merge_env: MergeEnv) -> None:
        """Clean worktree passes preflight."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Running pre-flight checks" in result.stdout
        assert "Pre-flight checks passed" in result.stdout

    def test_yok206_preflight_dirty_user_file(self, merge_env: MergeEnv) -> None:
        """Dirty user file fails preflight."""
        _write_file(merge_env.worktree / "my-code.js", "uncommitted user work\n")
        result = run_merge(merge_env)
        assert result.exit_code == 4
        assert "FAIL: Uncommitted non-Yoke files in worktree" in result.stderr
        assert "Pre-flight failed" in result.stderr

    def test_yok206_preflight_dirty_yoke_file(self, merge_env: MergeEnv) -> None:
        """Dirty Yoke file passes preflight."""
        wt = merge_env.worktree
        rel = "ouroboros/simulation-YOK-9999.md"
        _write_file(wt / rel, "# simulation\n")
        _git(wt, "add", rel)
        _git(wt, "commit", "-m", "add simulation report")
        _git(wt, "push", "origin", TEST_BRANCH)
        _write_file(wt / rel, "# simulation\ndirty report\n")

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "OK: Worktree clean" in result.stdout

    def test_yok206_preflight_incomplete_tasks(self, merge_env: MergeEnv) -> None:
        """Incomplete epic tasks block merge."""
        # Create custom DB with incomplete tasks
        custom_db = merge_env.tmpdir / "test-yoke.db"
        _create_epic_tasks_db(custom_db, task_status="implementing")

        # ``YOKE_DB_INIT_ALLOW=1`` opts the merge subprocess into
        # ambient bootstrap for any tables the service layer touches
        # beyond the minimal set staged here.  See the corresponding
        # comment in TestSimulationGate._run_with_sim_db.
        extra_env = {
            "YOKE_DB": str(custom_db),
            "YOKE_DB_INIT_ALLOW": "1",
        }
        result = run_merge(
            merge_env,
            extra_args=["42"],
            standalone=False,
            extra_env=extra_env,
        )
        # An epic ref is supplied, so the standalone permission is irrelevant;
        # re-run with it granted to prove the epic path is what gates here.
        result = run_merge(
            merge_env,
            extra_args=["42"],
            extra_env=extra_env,
        )
        assert result.exit_code == 1
        assert "FAIL: Incomplete tasks found" in result.stderr


# ===========================================================================
# Tests: Simulation gate
# ===========================================================================
class TestSimulationGate:
    """Integration simulation merge gate."""

    def _setup_sim_db(self, merge_env: MergeEnv, task_status: str = "done") -> Path:
        """Create a custom DB with simulation gate tables."""
        custom_db = merge_env.tmpdir / "test-yoke.db"
        _create_epic_tasks_db(custom_db, task_status=task_status)
        return custom_db

    def _run_with_sim_db(
        self,
        merge_env: MergeEnv,
        db_path: Path,
        extra_args_str: str = "42",
    ):
        """Run merge with custom sim DB and epic ID.

        The test's minimal sim DB intentionally stages only the tables
        the preflight reads.  ``YOKE_DB_INIT_ALLOW=1`` opts the merge
        subprocess into ambient bootstrap so any tables the service
        layer transitively touches (items, events, item_dependencies)
        are created on demand — the explicit opt-in path that the
        hardened ``db_router`` now requires.
        """
        args = extra_args_str.split()
        # The ambient bootstrap re-seeds ci_workflow_file inside the merge
        # subprocess's own DB, so the declaration check (honest since the
        # 12951 repair) would wait the full 120s ci_registration_timeout
        # for check-runs that can never register. A per-test machine home
        # pins the wait to 1s — get_seconds coerces <=0 back to the
        # default — without touching shared fixtures.
        machine_home = merge_env.tmpdir / "sim-machine-home"
        machine_home.mkdir(exist_ok=True)
        (machine_home / "config.json").write_text(
            '{"settings": {"ci_registration_timeout": "1", "ci_poll_interval": "1"}}',
            encoding="utf-8",
        )
        return run_merge(
            merge_env,
            extra_args=args,
            extra_env={
                "YOKE_DB": str(db_path),
                "YOKE_DB_INIT_ALLOW": "1",
                "YOKE_MACHINE_HOME": str(machine_home),
            },
        )

    def test_yok1180_preflight_missing_simulation_blocks(
        self, merge_env: MergeEnv
    ) -> None:
        """Missing simulation report blocks merge."""
        db = self._setup_sim_db(merge_env)
        result = self._run_with_sim_db(merge_env, db)
        assert result.exit_code == 1
        assert "FAIL: Integration simulation report not found" in result.stderr

    def test_yok1180_preflight_skip_simulation_override(
        self, merge_env: MergeEnv
    ) -> None:
        """--skip-simulation overrides missing report gate."""
        db = self._setup_sim_db(merge_env)
        result = self._run_with_sim_db(merge_env, db, "42 --skip-simulation")
        assert result.exit_code == 0
        assert (
            "WARN: Integration simulation gate overridden (--skip-simulation)"
            in result.stderr
        )

    def test_yok1180_preflight_plain_text_simulation_rejected(
        self, merge_env: MergeEnv
    ) -> None:
        """Plain text simulation rejected."""
        db = self._setup_sim_db(merge_env)
        _insert_plain_text_integration_simulation(db)
        result = self._run_with_sim_db(merge_env, db)
        assert result.exit_code == 1
        assert "FAIL: Integration simulation report not found" in result.stderr

    def test_yok1180_preflight_canonical_simulation_passes(
        self, merge_env: MergeEnv
    ) -> None:
        """Canonical JSON simulation passes."""
        db = self._setup_sim_db(merge_env)
        _insert_canonical_integration_simulation(db)
        result = self._run_with_sim_db(merge_env, db)
        assert result.exit_code == 0
        assert "OK: Canonical integration simulation report exists" in result.stdout


# ===========================================================================
# Tests: Branch validation
# ===========================================================================
class TestBranchValidation:
    """Standalone guard and legacy branch rejection."""

    def test_standalone_branch_rejected_without_permission(
        self, merge_env: MergeEnv,
    ) -> None:
        """Without --standalone the engine refuses an item branch."""
        repo = merge_env.repo

        # Create standalone branch
        _git(repo, "branch", "YOK-99")
        standalone_wt = merge_env.tmpdir / "worktree-yok99"
        _git(repo, "worktree", "add", str(standalone_wt), "YOK-99")
        _git(standalone_wt, "config", "user.email", "test@test.com")
        _git(standalone_wt, "config", "user.name", "Test")
        _write_file(standalone_wt / "standalone.txt", "standalone work\n")
        _git(standalone_wt, "add", "standalone.txt")
        _git(standalone_wt, "commit", "-m", "standalone work")
        _git(standalone_wt, "push", "origin", "YOK-99")

        result = run_merge(merge_env, branch="YOK-99", standalone=False)
        assert result.exit_code == 1
        assert "standalone item branch" in result.stderr

    def test_standalone_permission_clears_the_guard(
        self, merge_env: MergeEnv,
    ) -> None:
        """With --standalone the item-branch guard does not fire."""
        repo = merge_env.repo

        _git(repo, "branch", "YOK-99")
        standalone_wt = merge_env.tmpdir / "worktree-yok99ex"
        _git(repo, "worktree", "add", str(standalone_wt), "YOK-99")
        _git(standalone_wt, "config", "user.email", "test@test.com")
        _git(standalone_wt, "config", "user.name", "Test")
        _write_file(standalone_wt / "standalone.txt", "standalone work\n")
        _git(standalone_wt, "add", "standalone.txt")
        _git(standalone_wt, "commit", "-m", "standalone work")
        _git(standalone_wt, "push", "origin", "YOK-99")

        result = run_merge(merge_env, branch="YOK-99", standalone=True)
        # The guard must NOT have fired
        assert "standalone item branch" not in result.stderr
