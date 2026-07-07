"""Tests for yoke_core.domain.idea_readiness_repair_claim_coverage.

Covers:
- ``_classify_repair_action`` mapping for widen-only, narrow-only,
  mixed widen+narrow, non-recoverable, and empty inputs.
- ``attempt_claim_coverage_repair`` widen / narrow happy paths,
  idempotent re-entry on widen, and the four refusal cases
  (zero claims, multiple claims, mixed widen+narrow, non-recoverable).
- ``IdeaReadinessClaimCoverageRepairApplied`` event payload shape.
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
from yoke_core.domain.idea_readiness_repair import (
    CLASS_MIXED_STALE_COUNT,
    RepairOutcome,
)
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


def _seed_item(conn, *, item_id: int = 9001, project_id: int = 1) -> int:
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
    """Wrap a sqlite connection so the helper's ``conn.close()`` is a no-op.

    sqlite3.Connection.close is read-only and cannot be mocked directly;
    this transparent proxy lets the helper run without tearing down the
    pytest-owned connection mid-test.
    """

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


class TestClassifyRepairAction:
    def test_widen_only_returns_widen(self):
        assert repair._classify_repair_action({_WIDEN_CODE}) == "widen"

    def test_narrow_only_returns_narrow(self):
        assert repair._classify_repair_action({_NARROW_CODE}) == "narrow"

    def test_mixed_widen_and_narrow_refuses(self):
        assert (
            repair._classify_repair_action({_WIDEN_CODE, _NARROW_CODE})
            == "refuse"
        )

    def test_non_recoverable_code_refuses(self):
        assert (
            repair._classify_repair_action({_WIDEN_CODE, "UNRESOLVED_FUNCTION"})
            == "refuse"
        )

    def test_empty_refuses(self):
        assert repair._classify_repair_action(set()) == "refuse"


class TestAttemptClaimCoverageRepair:
    """End-to-end behavior against an in-memory path-claims DB."""

    def _register_single_claim(self, conn, *, item_id: int, paths: List[str]) -> int:
        actor = local_human(conn)
        _seed_project(conn)
        target_ids = [seed_target(conn, path_string=p) for p in paths]
        return register(
            conn, actor_id=actor, integration_target="main",
            target_ids=target_ids, item_id=item_id,
        )

    def test_pure_widen_succeeds(self, conn):
        item_id = _seed_item(conn, item_id=9201)
        seed_target(conn, path_string="src/bar.py")
        claim_id = self._register_single_claim(
            conn, item_id=item_id, paths=["src/foo.py"],
        )
        issues = [_claim_issue(_WIDEN_CODE, "src/bar.py")]
        with _patch_conn(conn), _patch_rerun("pass"):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is True
        assert outcome.classification == CLASS_MIXED_STALE_COUNT
        assert [p.path for p in outcome.repaired_paths] == ["src/bar.py"]
        assert outcome.field_written == ""
        row = conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()
        assert int(row[0]) == 2

    def test_idempotent_widen_no_op(self, conn):
        item_id = _seed_item(conn, item_id=9202)
        self._register_single_claim(
            conn, item_id=item_id, paths=["src/foo.py"],
        )
        issues = [_claim_issue(_WIDEN_CODE, "src/foo.py")]
        with _patch_conn(conn), _patch_rerun("pass"):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is True
        amendment = conn.execute(
            "SELECT amendment_kind FROM path_claim_amendments "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert amendment[0] == "widen"

    def test_pure_narrow_succeeds(self, conn, repo):
        item_id = _seed_item(conn, item_id=9203)
        actor = local_human(conn)
        _seed_project(conn, repo_path=str(repo))
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        claim_id = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta, tb], item_id=item_id,
        )
        issues = [_claim_issue(_NARROW_CODE, "src/bar.py")]
        with _patch_conn(conn), _patch_rerun("pass"):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is True
        amendment = conn.execute(
            "SELECT amendment_kind FROM path_claim_amendments "
            "WHERE claim_id = %s ORDER BY id DESC LIMIT 1",
            (claim_id,),
        ).fetchone()
        assert amendment[0] == "narrow"

    def test_zero_exclusive_claims_refused(self, conn):
        item_id = _seed_item(conn, item_id=9204)
        _seed_project(conn)
        issues = [_claim_issue(_WIDEN_CODE, "src/foo.py")]
        with _patch_conn(conn):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is False
        assert outcome.refused_paths[0]["reason"] == "no_exclusive_claim"

    def test_multiple_exclusive_claims_refused(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=9205)
        _seed_project(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        for tid in (ta, tb):
            register(
                conn, actor_id=actor, integration_target="main",
                target_ids=[tid], item_id=item_id,
            )
        issues = [_claim_issue(_WIDEN_CODE, "src/baz.py")]
        with _patch_conn(conn):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is False
        refused = outcome.refused_paths[0]
        assert refused["reason"] == "multiple_exclusive_claims"
        assert len(refused["claim_ids"]) == 2

    def test_non_recoverable_codes_refused(self, conn):
        item_id = _seed_item(conn, item_id=9206)
        issues = [
            _claim_issue(_WIDEN_CODE, "src/foo.py"),
            {"code": "UNRESOLVED_FUNCTION", "context": {}},
        ]
        with _patch_conn(conn):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=issues,
            )
        assert outcome.success is False
        assert (
            outcome.refused_paths[0]["reason"] == "non_recoverable_codes_present"
        )
        assert outcome.refused_paths[0]["codes"] == ["UNRESOLVED_FUNCTION"]

    # Mixed-axis partial-progress tests live in the
    # sibling module ``test_idea_readiness_repair_claim_coverage_mixed.py``
    # so this file stays under the 350-line authoring limit.


class TestRepairEventEmission:
    def test_widen_emits_event_with_expected_envelope(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=9301)
        _seed_project(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        seed_target(conn, path_string="src/bar.py")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        from yoke_core.domain.events import EmitResult

        capture: list[dict] = []

        def _capture(name, **kwargs):
            capture.append({"name": name, **kwargs})
            return EmitResult(
                ok=True, event_id="evt-test",
                envelope={"event_id": "evt-test"},
            )

        with _patch_conn(conn), _patch_rerun("pass"), \
             mock.patch("yoke_core.domain.events.emit_event", _capture):
            outcome = repair.attempt_claim_coverage_repair(
                item_id=item_id, issues=[_claim_issue(_WIDEN_CODE, "src/bar.py")],
            )
        assert outcome.success is True
        assert outcome.audit_emitted is True
        events = [
            e for e in capture
            if e["name"] == "IdeaReadinessClaimCoverageRepairApplied"
        ]
        assert len(events) == 1
        env = events[0]
        assert env["item_id"] == str(item_id)
        assert env["event_kind"] == "lifecycle"
        assert env["event_type"] == "readiness_repair"
        ctx = env["context"]
        assert ctx["action"] == "widen"
        assert ctx["rerun_verdict"] == "pass"
        assert ctx["field"] == ""
        assert [p["path"] for p in ctx["repaired_paths"]] == ["src/bar.py"]


class TestRepairOutcomeFromCoverage:
    def test_widen_success_payload_carries_repaired_paths(self):
        outcome = RepairOutcome(
            success=True, classification=CLASS_MIXED_STALE_COUNT, item_id=42,
            repaired_paths=[
                repair.RepairedPath(path="src/foo.py", recorded=0, actual=0),
            ],
            field_written="", rerun_verdict="pass", audit_emitted=True,
        )
        payload = outcome.to_payload()
        assert payload["success"] is True
        assert payload["repaired_paths"] == [
            {"path": "src/foo.py", "recorded": 0, "actual": 0},
        ]
        assert payload["rerun_verdict"] == "pass"
        assert "field_written" not in payload
        assert payload["audit_emitted"] is True
