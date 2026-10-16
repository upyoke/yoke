"""Run start answers new source questions outside locks; open lanes ask none."""

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_start
from yoke_core.domain.deployment_prepared_source import PreparedSource
from yoke_core.domain.deployment_run_carried_work_sources import (
    resolve_carried_items,
)
from yoke_core.domain.deployment_source_reads import (
    prepared_sources_only,
    source_read,
)
from yoke_core.domain.schema_read_scope import composition_reads

LANDED, OPEN, MOVED = "a" * 40, "b" * 40, "c" * 40


class _Repository:
    origin, location = "checkout", "/repo"

    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve_commit(self, ref: str) -> str:
        self.resolved.append(ref)
        return ref

    def carrying_commit(self, lane_commit, *, base, head, commits):
        return None

    def commit_time(self, sha: str) -> None:
        return None

    def warnings(self) -> list:
        return []


def _lane(conn: Any, item_id: int, commit_sha: str) -> None:
    conn.execute(
        "INSERT INTO item_worktrees (item_id, branch, path, lane_role, state, "
        "commit_sha, created_at, updated_at) VALUES (%s, %s, NULL, "
        "'implementation', 'active', %s, now(), now())",
        (item_id, f"YOK-{item_id}", commit_sha),
    )


def _derive(conn: Any, source: Any) -> None:
    project_id = conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()
    resolve_carried_items(
        conn,
        project_id=int(project_id[0]),
        source=source,
        base="base",
        head="head",
        commits=["d" * 40],
    )


def test_lane_commit_recorded_during_preparation_asks_no_locked_question(
    test_db: Any,
) -> None:
    insert_item(test_db, id=1, status="done", merged_at="2026-10-16T15:00:00Z")
    insert_item(test_db, id=2, status="implementing")
    _lane(test_db, 1, LANDED)
    _lane(test_db, 2, OPEN)
    repository = _Repository()
    with composition_reads():
        source = PreparedSource(test_db, ("carried_source", 1, ""), repository)
        _derive(test_db, source)
        test_db.execute(
            "UPDATE item_worktrees SET commit_sha=%s WHERE item_id=2", (MOVED,)
        )
        with prepared_sources_only():
            _derive(test_db, source)
    assert repository.resolved == [LANDED]


class _Connection:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


def _start(monkeypatch: pytest.MonkeyPatch, questions) -> tuple[Any, list, Any]:
    prepared: list[Any] = []
    monkeypatch.setattr(deployment_run_start, "_prepare", lambda conn, run_id: None)

    def admit(conn, run_id, candidate_containment):
        with prepared_sources_only():
            for key in questions(conn):
                source_read(conn, key, lambda key=key: prepared.append(key))
        return None

    monkeypatch.setattr(deployment_run_start, "_admit", admit)
    conn = _Connection()
    return deployment_run_start.start_run(conn, "run-1", None), prepared, conn


def test_new_source_question_is_prepared_unlocked_then_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, prepared, conn = _start(
        monkeypatch, lambda conn: [("fact", "new"), ("fact", "later")]
    )
    assert result is None
    assert prepared == [("fact", "new"), ("fact", "later")]
    assert conn.rollbacks == 2


def test_exhausted_preparations_name_the_missing_source_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = iter(range(1, 100))
    result, prepared, conn = _start(
        monkeypatch, lambda conn: [("fact", next(attempts))]
    )
    assert result.startswith("Error: deployment_source_preparation_changed")
    assert "source fact ('fact', 8)" in result
    assert "still new after 8 unlocked preparations" in result
    assert len(prepared) == 7
    assert conn.rollbacks == 8
