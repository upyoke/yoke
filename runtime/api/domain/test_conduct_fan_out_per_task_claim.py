"""Integration test for conduct fan-out per-task work-claim lifecycle.

AC-8/AC-9/AC-11 surface. Exercises acquire → resolve → lint-authorise →
release across multi-worktree and same-worktree fan-out shapes. The
test simulates conduct's claim lifecycle with a disposable-Postgres DB
double and direct DB writes; the handler-level acquire/release coverage lives in
``runtime/api/domain/handlers/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.lint_session_cwd_validate import validate_targets
from yoke_core.domain.session_claimed_worktrees import claimed_worktrees


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, worktree TEXT, project_id INTEGER,
            status TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
            worktree TEXT, PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            item_id INTEGER, epic_id INTEGER, task_num INTEGER,
            process_key TEXT, released_at TEXT
        );
        """,
    )
    yield c
    c.close()


def _acquire(conn, *, session_id, epic_id, task_num) -> int:
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, epic_id, "
        "task_num) VALUES (%s, 'epic_task', %s, %s) RETURNING id",
        (session_id, epic_id, task_num),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


def _release(conn, claim_id, *, when="2026-05-27T13:00:00Z") -> None:
    conn.execute(
        "UPDATE work_claims SET released_at = %s WHERE id = %s",
        (when, claim_id),
    )
    conn.commit()


def _seed_fanout(
    conn, repo: Path, *, item_id: int, session_id: str,
    lanes: Iterable[Tuple[int, str]],
) -> dict:
    """Materialise an epic with the given (task_num, branch) lanes,
    each acquired by ``session_id``. Returns ``{task_num: claim_id}``.
    """
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (1, 'yoke')",
    )
    register_machine_checkout(repo.parent / "machine-config", repo, 1)
    conn.execute(
        "INSERT INTO items (id, worktree, project_id) VALUES (%s, NULL, 1)",
        (item_id,),
    )
    claims: dict = {}
    for task_num, branch in lanes:
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, worktree) "
            "VALUES (%s, %s, %s)",
            (item_id, task_num, branch),
        )
        (repo / ".worktrees" / branch).mkdir(parents=True, exist_ok=True)
        claims[task_num] = _acquire(
            conn, session_id=session_id,
            epic_id=item_id, task_num=task_num,
        )
    return claims


def _write_target(repo: Path, branch: str, name: str = "x.py") -> Path:
    target = repo / ".worktrees" / branch / "src" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# stub")
    return target


# Multi-worktree case: >=2 distinct worktree paths across tasks.


class TestMultiWorktreeFanOutLifecycle:
    LANES = (
        (1, "YOK-1872-substrate"),
        (10, "YOK-1872-propagation"),
        (20, "YOK-1872-integration"),
    )

    def test_n_claims_materialise_before_dispatch(self, conn, tmp_path):
        # AC-8(a) — N task worktrees produce N epic_task claim rows.
        _seed_fanout(
            conn, tmp_path / "repo", item_id=1872,
            session_id="sid-orch", lanes=self.LANES,
        )
        active = conn.execute(
            "SELECT epic_id, task_num FROM work_claims "
            "WHERE session_id='sid-orch' AND target_kind='epic_task' "
            "AND released_at IS NULL ORDER BY task_num"
        ).fetchall()
        assert [(r["epic_id"], r["task_num"]) for r in active] == [
            (1872, 1), (1872, 10), (1872, 20),
        ]

    def test_each_claim_resolves_to_its_task_worktree(self, conn, tmp_path):
        # AC-8(b) — each row's resolved worktree matches epic_tasks.worktree.
        repo = tmp_path / "repo"
        _seed_fanout(
            conn, repo, item_id=1872, session_id="sid-orch",
            lanes=self.LANES,
        )
        resolved = claimed_worktrees(conn, session_id="sid-orch")
        assert [(c.task_num, c.worktree_path) for c in resolved] == [
            (1, str(repo / ".worktrees" / "YOK-1872-substrate")),
            (10, str(repo / ".worktrees" / "YOK-1872-propagation")),
            (20, str(repo / ".worktrees" / "YOK-1872-integration")),
        ]

    def test_lint_authorises_each_task_worktree(self, conn, tmp_path):
        # AC-8(d) — no WORKTREE-BINDING REFUSAL per dispatched subagent.
        repo = tmp_path / "repo"
        _seed_fanout(
            conn, repo, item_id=1872, session_id="sid-orch",
            lanes=self.LANES,
        )
        for _tn, branch in self.LANES:
            target = _write_target(repo, branch)
            verdict = validate_targets(
                conn, session_id="sid-orch", targets=(str(target),),
            )
            assert verdict.allow is True, (
                f"lane {branch} should be writable; got: {verdict}"
            )

    def test_release_clears_authority_per_task(self, conn, tmp_path):
        # AC-8(c) — released_at set; resolver drops the released lane
        # while sibling lanes remain. (validate_targets cannot assert
        # denial here because pytest tmp_path lands under the lint's
        # free-path allowlist; the resolver is the semantic authority.)
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn, repo, item_id=1872, session_id="sid-orch",
            lanes=self.LANES,
        )
        _release(conn, claims[10])
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE id = %s",
            (claims[10],),
        ).fetchone()
        assert row["released_at"] is not None

        resolved_paths = [
            c.worktree_path
            for c in claimed_worktrees(conn, session_id="sid-orch")
        ]
        prop = str(repo / ".worktrees" / "YOK-1872-propagation")
        substrate = str(repo / ".worktrees" / "YOK-1872-substrate")
        integration = str(repo / ".worktrees" / "YOK-1872-integration")
        assert prop not in resolved_paths
        assert substrate in resolved_paths
        assert integration in resolved_paths

        # Sibling lane still passes the lint.
        allowed = _write_target(repo, "YOK-1872-substrate")
        assert validate_targets(
            conn, session_id="sid-orch", targets=(str(allowed),),
        ).allow is True

        # A worktree the session never claimed and that lives outside
        # the free-path allowlist still denies — proves the per-task
        # claim shape is the only authority gate (no inheritance).
        rogue = "/opt/other-repo/.worktrees/YOK-1872-rogue/x.py"
        verdict = validate_targets(
            conn, session_id="sid-orch", targets=(rogue,),
        )
        assert verdict.allow is False
        assert "YOK-1872-rogue" in verdict.offending_target

    def test_full_release_clears_all_authority(self, conn, tmp_path):
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn, repo, item_id=1872, session_id="sid-orch",
            lanes=self.LANES,
        )
        for cid in claims.values():
            _release(conn, cid)
        assert claimed_worktrees(conn, session_id="sid-orch") == []


# Same-worktree case: multiple tasks share one branch.


class TestSameWorktreeFanOutLifecycle:
    LANES = (
        (5, "YOK-1873-shared"),
        (6, "YOK-1873-shared"),
    )

    def test_two_claims_one_worktree_authorise_path(self, conn, tmp_path):
        repo = tmp_path / "repo"
        _seed_fanout(
            conn, repo, item_id=1873, session_id="sid-orch",
            lanes=self.LANES,
        )
        resolved = claimed_worktrees(conn, session_id="sid-orch")
        assert len(resolved) == 2
        shared = str(repo / ".worktrees" / "YOK-1873-shared")
        assert all(c.worktree_path == shared for c in resolved)
        target = _write_target(repo, "YOK-1873-shared")
        assert validate_targets(
            conn, session_id="sid-orch", targets=(str(target),),
        ).allow is True

    def test_release_one_keeps_authority_via_sibling(self, conn, tmp_path):
        # Conduct may release one task's claim while the sibling stays
        # active; shared worktree stays authorised through the survivor.
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn, repo, item_id=1873, session_id="sid-orch",
            lanes=self.LANES,
        )
        _release(conn, claims[5])
        target = _write_target(repo, "YOK-1873-shared")
        assert validate_targets(
            conn, session_id="sid-orch", targets=(str(target),),
        ).allow is True

    def test_release_both_clears_authority(self, conn, tmp_path):
        # Releasing every per-task claim drains the session's resolver
        # surface — claimed_worktrees returns no rows. (The lint's
        # no-claims branch short-circuits to allow=True so the resolver
        # is the semantic authority here.)
        repo = tmp_path / "repo"
        claims = _seed_fanout(
            conn, repo, item_id=1873, session_id="sid-orch",
            lanes=self.LANES,
        )
        for cid in claims.values():
            _release(conn, cid)
        assert claimed_worktrees(conn, session_id="sid-orch") == []


# Item + epic_task coexistence — no sibling inheritance.


class TestItemAndEpicTaskClaimsCoexist:
    def test_both_claims_coexist_and_authorise_correctly(
        self, conn, tmp_path,
    ):
        repo = tmp_path / "repo"
        conn.execute(
            "INSERT INTO projects (id, slug) VALUES (1, 'yoke')",
        )
        register_machine_checkout(repo.parent / "machine-config", repo, 1)
        conn.execute(
            "INSERT INTO items (id, worktree, project_id) "
            "VALUES (1872, 'YOK-1872', 1)"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, worktree) "
            "VALUES (1872, 1, 'YOK-1872-substrate')"
        )
        for branch in ("YOK-1872", "YOK-1872-substrate"):
            (repo / ".worktrees" / branch).mkdir(parents=True, exist_ok=True)
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id) "
            "VALUES ('sid-orch', 'item', 1872)"
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, epic_id, "
            "task_num) VALUES ('sid-orch', 'epic_task', 1872, 1)"
        )
        conn.commit()
        paths = sorted(
            c.worktree_path
            for c in claimed_worktrees(conn, session_id="sid-orch")
        )
        assert str(repo / ".worktrees" / "YOK-1872") in paths
        assert str(repo / ".worktrees" / "YOK-1872-substrate") in paths
