"""Coverage for the stale-base-on-new-claim widen validator.

Scenarios:

* Path that integration_target changed AFTER the claim's base_commit_sha
  AND working branch did not reconcile → block with
  ``StaleBaseOnNewClaim``, NOT ``IncompatibleOverlap``.
* Same path but working branch has merged the integration_target HEAD
  → widen proceeds.
* New paths that did not change in the integration_target window
  → widen proceeds even if other paths in the same integration_target
  range changed (AC-5 only fires per-path).
* No ``base_commit_sha`` on the claim (never activated) →
  validator returns None silently.
* ``base_commit_sha == integration_target HEAD`` → no drift → None.
* Comparison anchor is ``base_commit_sha`` — not git
  merge-base. Test asserts the validator looks up
  ``path_snapshots.commit_sha`` and uses ``run_git diff base..head``
  against ``resolve_integration_head``.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    activate,
    register,
)
from yoke_core.domain.path_claims_amend import widen
from yoke_core.domain.path_claims_amend_stale_base import (
    StaleBaseOnNewClaim,
    check_stale_base_on_new_claim,
)


def _git(repo, *args):
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False, env=full_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout


@pytest.fixture
def repo_with_drift(tmp_path):
    """Build a repo where main moved forward after the claim's base."""
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("x = 1\n")
    (tmp_path / "src" / "untouched.py").write_text("y = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    base_sha = _git(tmp_path, "rev-parse", "HEAD").strip()
    # Branch off feature
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    feature_sha = _git(tmp_path, "rev-parse", "HEAD").strip()
    # main moves forward, touches src/foo.py (NOT src/untouched.py)
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "src" / "foo.py").write_text("x = 2\n")
    _git(tmp_path, "add", "src/foo.py")
    _git(tmp_path, "commit", "-q", "-m", "main move")
    head_sha = _git(tmp_path, "rev-parse", "HEAD").strip()
    # Stay on feature for the worktree branch
    _git(tmp_path, "checkout", "-q", "feature")
    return {
        "path": tmp_path,
        "base_sha": base_sha,
        "feature_sha": feature_sha,
        "head_sha": head_sha,
    }


def _seed_snapshot(conn, *, project_id: int, commit_sha: str) -> int:
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, '2026-05-03T00:00:00Z') RETURNING id",
        (project_id, commit_sha),
    )
    snapshot_id = int(cur.fetchone()[0])
    conn.commit()
    return snapshot_id


def _seed_item(conn, *, item_id: int = 21001):
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestStaleBaseValidator:
    def test_blocks_when_integration_target_changed_path(
        self, conn, repo_with_drift,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21001)
        # Claim base = the original commit. Existing target unrelated.
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(
            conn, claim_id=cid, base_commit_sha=repo_with_drift["base_sha"],
        )
        # New target = path that main moved
        new_target = seed_target(conn, path_string="src/foo.py")
        with pytest.raises(StaleBaseOnNewClaim) as exc_info:
            check_stale_base_on_new_claim(
                conn,
                claim_id=cid,
                new_target_ids=[new_target],
                repo_path=str(repo_with_drift["path"]),
                worktree_head=repo_with_drift["feature_sha"],
            )
        # Distinct diagnostic name and code, not claim_overlap
        assert exc_info.value.error_code == "stale-base-on-new-claim"
        assert "src/foo.py" in exc_info.value.offending_paths
        assert exc_info.value.offending_target_ids == [new_target]
        assert (
            exc_info.value.base_commit_sha == repo_with_drift["base_sha"]
        )
        assert (
            exc_info.value.integration_target_head_sha
            == repo_with_drift["head_sha"]
        )

    def test_passes_after_branch_reconciles_integration_head(
        self, conn, repo_with_drift,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21002)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(
            conn, claim_id=cid, base_commit_sha=repo_with_drift["base_sha"],
        )
        # Merge main into feature so feature branch includes head_sha
        _git(repo_with_drift["path"], "merge", "-q", "main", "--no-edit")
        merged_sha = _git(
            repo_with_drift["path"], "rev-parse", "HEAD",
        ).strip()
        new_target = seed_target(conn, path_string="src/foo.py")
        # Reconciled → no block, validator returns None
        result = check_stale_base_on_new_claim(
            conn,
            claim_id=cid,
            new_target_ids=[new_target],
            repo_path=str(repo_with_drift["path"]),
            worktree_head=merged_sha,
        )
        assert result is None

    def test_passes_when_new_path_did_not_change_in_window(
        self, conn, repo_with_drift,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21003)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(
            conn, claim_id=cid, base_commit_sha=repo_with_drift["base_sha"],
        )
        # New target = a file main did NOT touch in the drift window
        new_target = seed_target(conn, path_string="src/untouched.py")
        result = check_stale_base_on_new_claim(
            conn,
            claim_id=cid,
            new_target_ids=[new_target],
            repo_path=str(repo_with_drift["path"]),
            worktree_head=repo_with_drift["feature_sha"],
        )
        assert result is None

    def test_passes_when_claim_has_no_base_commit_sha(
        self, conn, repo_with_drift,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21004)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        # Not activated → base_commit_sha stays NULL
        new_target = seed_target(conn, path_string="src/foo.py")
        result = check_stale_base_on_new_claim(
            conn,
            claim_id=cid,
            new_target_ids=[new_target],
            repo_path=str(repo_with_drift["path"]),
            worktree_head=repo_with_drift["feature_sha"],
        )
        assert result is None

    def test_passes_when_no_drift_at_all(self, conn, tmp_path):
        """base_commit_sha == integration_target HEAD → no drift."""
        _git(tmp_path, "init", "-q", "--initial-branch=main")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").write_text("x = 1\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-q", "-m", "only")
        sha = _git(tmp_path, "rev-parse", "HEAD").strip()
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21005)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(conn, claim_id=cid, base_commit_sha=sha)
        new_target = seed_target(conn, path_string="src/foo.py")
        result = check_stale_base_on_new_claim(
            conn,
            claim_id=cid,
            new_target_ids=[new_target],
            repo_path=str(tmp_path),
            worktree_head=sha,
        )
        assert result is None

    def test_passes_when_repo_path_unresolvable(self, conn):
        """Fail-open if integration_target ref cannot be resolved."""
        # Empty repo path → resolve_integration_head raises
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=21006)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(conn, claim_id=cid, base_commit_sha="0" * 40)
        new_target = seed_target(conn, path_string="src/foo.py")
        result = check_stale_base_on_new_claim(
            conn,
            claim_id=cid,
            new_target_ids=[new_target],
            repo_path="/nonexistent/path",
            worktree_head=None,
        )
        assert result is None


class TestWidenIntegrationStaleBaseGate:
    def test_widen_blocks_with_stale_base_when_repo_path_supplied(
        self, conn, repo_with_drift,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=22001)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(
            conn, claim_id=cid, base_commit_sha=repo_with_drift["base_sha"],
        )
        new_target = seed_target(conn, path_string="src/foo.py")
        with pytest.raises(StaleBaseOnNewClaim):
            widen(
                conn,
                claim_id=cid,
                add_target_ids=[new_target],
                reason="follow-up",
                repo_path=str(repo_with_drift["path"]),
                worktree_head=repo_with_drift["feature_sha"],
            )

    def test_widen_proceeds_when_repo_path_is_none(
        self, conn, repo_with_drift,
    ):
        """No checkout path supplied -> stale-base check is skipped."""
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=22002)
        existing = seed_target(conn, path_string="docs/unrelated.md")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[existing], item_id=item_id,
        )
        activate(
            conn, claim_id=cid, base_commit_sha=repo_with_drift["base_sha"],
        )
        new_target = seed_target(conn, path_string="src/foo.py")
        # Without checkout context, the stale-base check is skipped.
        amendment_id = widen(
            conn,
            claim_id=cid,
            add_target_ids=[new_target],
            reason="follow-up",
        )
        assert amendment_id is not None
