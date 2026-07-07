"""Mixed widen+narrow partial-progress tests for claim-coverage auto-repair.

Sibling of :mod:`test_idea_readiness_repair_claim_coverage`. Lives in its
own module to keep both files under the 350-line authoring limit. Covers
AC-2 / AC-3 / AC-4 from YOK-1825: when the readiness check surfaces both
``FILE_BUDGET_NOT_IN_CLAIM`` and ``CLAIM_NOT_IN_FILE_BUDGET`` codes, the
auto-repair runs both ``_apply_widen`` and ``_apply_narrow`` and
aggregates the results instead of refusing all-or-nothing.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import List
from unittest import mock

import pytest

from yoke_core.domain import idea_readiness_repair_claim_coverage as repair
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.idea_readiness_repair import CLASS_MIXED_STALE_COUNT
from yoke_core.domain.path_claims import register
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)


_WIDEN_CODE = "FILE_BUDGET_NOT_IN_CLAIM"
_NARROW_CODE = "CLAIM_NOT_IN_FILE_BUDGET"


def _git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / "README.md").write_text("# repo\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _seed_item(conn, *, item_id: int, project_id: int = 1) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()
    return item_id


def _seed_project(
    conn, *, project_id: int = 1, slug: str = "yoke", repo_path: str = "",
) -> None:
    checkout = Path(repo_path)
    if repo_path and checkout.is_dir():
        register_machine_checkout(checkout.parent, checkout, project_id)
    else:
        clear_machine_checkout(project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, default_branch, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, 'main', 'YOK', '2026-05-01T00:00:00Z') "
        "ON CONFLICT(id) DO UPDATE SET slug=excluded.slug",
        (project_id, slug, "Yoke"),
    )
    conn.commit()


def _claim_issue(code: str, path: str) -> dict:
    return {"code": code, "context": {"path": path}}


class _NoCloseConn:
    """Transparent proxy so the helper's ``conn.close()`` is a no-op."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


@contextmanager
def _patch_conn(conn):
    with mock.patch.object(repair, "_open_conn", return_value=_NoCloseConn(conn)):
        yield


@contextmanager
def _patch_rerun(verdict: str = "pass", issues: List[dict] | None = None):
    with mock.patch.object(
        repair, "_rerun_readiness", return_value=(verdict, issues or []),
    ):
        yield


def _seed_claim(conn, *, item_id: int, repo_path: str,
                owned_paths: List[str]) -> None:
    actor = local_human(conn)
    _seed_item(conn, item_id=item_id)
    _seed_project(conn, repo_path=repo_path)
    target_ids = [seed_target(conn, path_string=p) for p in owned_paths]
    register(
        conn, actor_id=actor, integration_target="main",
        target_ids=target_ids, item_id=item_id,
    )


class TestAttemptClaimCoverageRepairMixed:
    """AC-2 / AC-3 / AC-4 — partial-progress for mixed widen+narrow."""

    def test_both_axes_repairable_lands_both(self, conn, repo):
        """AC-2: both axes individually repairable -> both land, success=True."""
        _seed_claim(
            conn, item_id=9207, repo_path=str(repo),
            owned_paths=["src/keep.py", "src/drop.py"],
        )
        seed_target(conn, path_string="src/add.py")
        issues = [_claim_issue(_WIDEN_CODE, "src/add.py"),
                  _claim_issue(_NARROW_CODE, "src/drop.py")]
        with _patch_conn(conn), _patch_rerun("pass"):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=9207, issues=issues,
            )
        assert outcome.success is True
        assert outcome.classification == CLASS_MIXED_STALE_COUNT
        assert {p.path for p in outcome.repaired_paths} == {
            "src/add.py", "src/drop.py"}
        assert outcome.refused_paths == []
        assert outcome.rerun_verdict == "pass"

    def test_widen_blocked_narrow_clean(self, conn, repo):
        """AC-3: narrow lands; widen reports residual; success mirrors rerun."""
        # src/missing.py intentionally not seeded -> resolver raises
        # UnknownPathTargets; _apply_widen catches it as widen_failed.
        _seed_claim(
            conn, item_id=9208, repo_path=str(repo),
            owned_paths=["src/keep.py", "src/drop.py"],
        )
        issues = [_claim_issue(_WIDEN_CODE, "src/missing.py"),
                  _claim_issue(_NARROW_CODE, "src/drop.py")]
        with _patch_conn(conn), _patch_rerun(
            "block", [_claim_issue(_WIDEN_CODE, "src/missing.py")],
        ):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=9208, issues=issues,
            )
        assert outcome.success is False
        assert {p.path for p in outcome.repaired_paths} == {"src/drop.py"}
        assert len(outcome.refused_paths) == 1
        assert outcome.refused_paths[0]["reason"] == "widen_failed"
        assert outcome.rerun_verdict == "block"

    def test_both_blocked_refused_before_mutation(self, conn):
        """AC-4: both sides blocked -> success=False, refused_paths covers both."""
        # Empty checkout path -> narrow refuses before mutating coverage.
        _seed_claim(
            conn, item_id=9209, repo_path="", owned_paths=["src/keep.py"],
        )
        issues = [_claim_issue(_WIDEN_CODE, "src/unseeded.py"),
                  _claim_issue(_NARROW_CODE, "src/also_unseeded.py")]
        with _patch_conn(conn):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=9209, issues=issues,
            )
        assert outcome.success is False
        assert outcome.repaired_paths == []
        reasons = {entry["reason"] for entry in outcome.refused_paths}
        assert "widen_failed" in reasons
        assert "narrow_boundary_checkout_missing" in reasons
        assert outcome.rerun_verdict == ""
        assert outcome.error == "repair refused before mutation"
