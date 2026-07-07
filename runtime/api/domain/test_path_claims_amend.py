"""Coverage for the amendment surface (widen / narrow / cancel-amendment)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    activate,
    get_claim,
    register,
)
from yoke_core.domain.path_claims_amend import (
    AmendmentNotFound,
    CannotAmendClaim,
    NarrowWouldOrphanCommittedWork,
    cancel_amendment,
    narrow,
    widen,
)
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.path_targets_planning import plan_path_target


def _git(repo, *args):
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False, env=full_env,
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


def _seed_item(conn, *, item_id: int = 9001):
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestWiden:
    def test_widen_adds_targets_and_records_amendment(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        amendment_id = widen(
            conn, claim_id=cid, add_target_ids=[tb], reason="follow-up",
        )
        claim = get_claim(conn, cid)
        assert sorted(claim["target_ids"]) == sorted([ta, tb])
        row = conn.execute(
            "SELECT amendment_kind, payload, reason FROM "
            "path_claim_amendments WHERE id = %s",
            (amendment_id,),
        ).fetchone()
        assert row[0] == "widen"
        assert json.loads(row[1])["added"] == [tb]
        assert row[2] == "follow-up"

    def test_widen_no_op_when_already_covered(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        amendment_id = widen(
            conn, claim_id=cid, add_target_ids=[target], reason="re-affirm",
        )
        row = conn.execute(
            "SELECT amendment_kind, payload FROM path_claim_amendments "
            "WHERE id = %s",
            (amendment_id,),
        ).fetchone()
        assert row[0] == "widen"
        payload = json.loads(row[1])
        assert payload["added"] == []
        assert "no_op_reason" in payload

    def test_widen_rejects_when_creating_active_overlap(self, conn):
        actor = local_human(conn)
        item_a = _seed_item(conn, item_id=9101)
        item_b = _seed_item(conn, item_id=9102)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        # Active claim on tb on the same integration target
        first = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_a,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        # Second planned claim on ta — widening to include tb conflicts
        second = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_b,
        )
        with pytest.raises(IncompatibleOverlap):
            widen(
                conn, claim_id=second, add_target_ids=[tb], reason="bad widen",
            )

    def test_widen_allows_active_claim_for_boundary_remediation(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=9201)
        target = seed_target(conn, path_string="src/foo.py")
        extra = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        activate(conn, claim_id=cid, base_commit_sha=SNAP)
        widen(conn, claim_id=cid, add_target_ids=[extra], reason="late widen")
        claim = get_claim(conn, cid)
        assert sorted(claim["target_ids"]) == sorted([target, extra])


class TestNarrow:
    def test_narrow_drops_target_when_no_committed_touch(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta, tb], item_id=item_id,
        )
        amendment_id = narrow(
            conn,
            claim_id=cid,
            drop_target_ids=[tb],
            reason="dropping unused",
            repo_path=str(repo),
        )
        claim = get_claim(conn, cid)
        assert claim["target_ids"] == [ta]
        row = conn.execute(
            "SELECT amendment_kind, payload FROM path_claim_amendments "
            "WHERE id = %s",
            (amendment_id,),
        ).fetchone()
        assert row[0] == "narrow"
        assert json.loads(row[1])["removed"] == [tb]

    def test_narrow_abandons_dropped_planned_target(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        keep = seed_target(conn, path_string="src/foo.py")
        drop = plan_path_target(
            conn,
            project_id=1,
            path_string="src/future.py",
            kind=KIND_FILE,
            item_id=item_id,
        )
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[keep, drop], item_id=item_id,
        )
        narrow(
            conn,
            claim_id=cid,
            drop_target_ids=[drop],
            reason="dropping planned file",
            repo_path=str(repo),
        )
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (drop,),
        ).fetchone()["materialization_state"]
        assert state == "abandoned"

    def test_narrow_rejects_when_dropping_committed_path(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta, tb], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        (repo / "src" / "bar.py").write_text("print('y')\n")
        _git(repo, "add", "src/foo.py", "src/bar.py")
        _git(repo, "commit", "-q", "-m", "two files")
        with pytest.raises(NarrowWouldOrphanCommittedWork) as excinfo:
            narrow(
                conn,
                claim_id=cid,
                drop_target_ids=[tb],
                reason="bad narrow",
                repo_path=str(repo),
            )
        assert "src/bar.py" in excinfo.value.offending_paths
        assert excinfo.value.offending_target_ids  # AC-9A: ids surface

    def test_narrow_rejects_dropping_all_targets(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(Exception, match="at least one target must remain"):
            narrow(
                conn,
                claim_id=cid,
                drop_target_ids=[target],
                reason="empty out",
                repo_path=str(repo),
            )


class TestCancelAmendment:
    def test_cancel_widen_removes_added_targets(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        amendment_id = widen(
            conn, claim_id=cid, add_target_ids=[tb], reason="add",
        )
        cancel_amendment(
            conn, claim_id=cid, amendment_id=amendment_id, reason="undo",
        )
        claim = get_claim(conn, cid)
        assert claim["target_ids"] == [ta]
        # Audit trail still has both rows
        rows = conn.execute(
            "SELECT amendment_kind FROM path_claim_amendments "
            "WHERE claim_id = %s ORDER BY id",
            (cid,),
        ).fetchall()
        assert [r[0] for r in rows] == ["widen", "cancel"]

    def test_cancel_narrow_re_adds_dropped_targets(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta, tb], item_id=item_id,
        )
        amendment_id = narrow(
            conn,
            claim_id=cid,
            drop_target_ids=[tb],
            reason="drop",
            repo_path=str(repo),
        )
        cancel_amendment(
            conn, claim_id=cid, amendment_id=amendment_id, reason="undo",
        )
        claim = get_claim(conn, cid)
        assert sorted(claim["target_ids"]) == sorted([ta, tb])

    def test_cancel_unknown_amendment_raises(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(AmendmentNotFound):
            cancel_amendment(
                conn, claim_id=cid, amendment_id=999_999, reason="bogus",
            )
