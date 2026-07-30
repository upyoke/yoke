"""In-process integration coverage for the advance preflight gate evals.

Exercises the four ``advance.preflight.*`` internal handlers against a
seeded Postgres authority. Each handler is a thin wrapper over an existing
gate domain function; these tests prove the wrapper resolves the item
target, runs the gate server-side against real DB state, and returns the
verdict in its declared response shape for both pass and block cases. This
is the local / in-process leg of the ALL-MODES contract; the relay leg is
covered by ``test_advance_implementation_preflight``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import advance_preflight_gate_evals as gates


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-preflight"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _ensure_dependency_schema(conn) -> None:
    """The dependency table is shepherd-owned, not part of core cmd_init."""
    from yoke_core.domain import shepherd_init

    shepherd_init.cmd_init(conn)


def _insert_dep(conn, *, dependent: int, blocking: int, satisfaction: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "created_at) VALUES (%s, %s, 'activation', %s, 'test', %s)",
        (f"YOK-{dependent}", f"YOK-{blocking}", satisfaction, iso8601_now()),
    )
    conn.commit()


def _seed_target(conn, project_id: int, path: str) -> int:
    return int(
        conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at) "
            "VALUES (%s, 'file', %s, 1, %s) RETURNING id",
            (project_id, path, iso8601_now()),
        ).fetchone()[0]
    )


def _seed_planned_claim(conn, *, item_id, actor_id, target_ids) -> int:
    claim_id = int(
        conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, registered_at) "
            "VALUES ('planned', 'exclusive', %s, %s, 'main', %s) RETURNING id",
            (actor_id, item_id, iso8601_now()),
        ).fetchone()[0]
    )
    for target_id in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, %s)",
            (claim_id, target_id, iso8601_now()),
        )
    conn.commit()
    return claim_id


class TestHardBlocksEval:
    def test_pass_when_no_blockers(self, db):
        conn = connect_test_db(db)
        try:
            _ensure_dependency_schema(conn)
            insert_item(conn, id=8201, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = gates.handle_hard_blocks(
            _envelope("advance.preflight.hard_blocks", item_id=8201,
                      payload={"gate_filter": "activation"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["blockers"] == []
        gates.HardBlocksEvalResponse(**outcome.result_payload)

    def test_block_on_unsatisfied_activation_dependency(self, db):
        conn = connect_test_db(db)
        try:
            _ensure_dependency_schema(conn)
            actor = seed_human_actor(conn)
            insert_item(conn, id=8202, source=str(actor))
            insert_item(conn, id=8210, status="implementing", source=str(actor))
            _insert_dep(conn, dependent=8202, blocking=8210,
                        satisfaction="status:done")
        finally:
            conn.close()
        outcome = gates.handle_hard_blocks(
            _envelope("advance.preflight.hard_blocks", item_id=8202,
                      payload={"gate_filter": "activation"})
        )
        assert outcome.primary_success, outcome.error
        blockers = outcome.result_payload["blockers"]
        assert len(blockers) == 1
        assert "YOK-8210" in blockers[0]


class TestAcPresenceEval:
    def test_pass_with_canonical_acs(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=8220, source=str(seed_human_actor(conn)),
                spec="## Acceptance Criteria\n- [ ] AC-1: does X\n",
            )
        finally:
            conn.close()
        outcome = gates.handle_ac_presence(
            _envelope("advance.preflight.ac_presence", item_id=8220)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["canonical"] == 1
        assert outcome.result_payload["title"] is not None
        gates.AcPresenceEvalResponse(**outcome.result_payload)

    def test_block_without_acs(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=8221, source=str(seed_human_actor(conn)),
                        spec="no checkboxes here")
        finally:
            conn.close()
        outcome = gates.handle_ac_presence(
            _envelope("advance.preflight.ac_presence", item_id=8221)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["canonical"] == 0
        assert outcome.result_payload["title"] is not None

    def test_missing_item_reports_null_title(self, db):
        outcome = gates.handle_ac_presence(
            _envelope("advance.preflight.ac_presence", item_id=999999)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["title"] is None


class TestFileBudgetEval:
    def test_pass_with_resolved_file_budget(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=8230, source=str(seed_human_actor(conn)),
                spec="## File Budget\n\n- `runtime/api/domain/foo.py` — does X.\n",
            )
        finally:
            conn.close()
        outcome = gates.handle_file_budget(
            _envelope("advance.preflight.file_budget", item_id=8230)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["verdict"] == "pass"
        gates.FileBudgetEvalResponse(**outcome.result_payload)

    def test_block_without_file_budget_section(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=8231, source=str(seed_human_actor(conn)),
                        spec="## Acceptance Criteria\n- [ ] AC-1: x\n")
        finally:
            conn.close()
        outcome = gates.handle_file_budget(
            _envelope("advance.preflight.file_budget", item_id=8231)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["verdict"] == "block"
        assert "File Budget" in outcome.result_payload["reason"]


class TestSpecCoverageEval:
    _budget_spec = (
        "## File Budget\n\n"
        "- `runtime/api/domain/foo.py` — covered.\n"
        "- `runtime/api/domain/bar.py` — maybe covered.\n"
    )

    def test_pass_when_claim_covers_all_budget_paths(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=8240, source=str(actor), spec=self._budget_spec)
            pid = _project_id(conn, 8240)
            t1 = _seed_target(conn, pid, "runtime/api/domain/foo.py")
            t2 = _seed_target(conn, pid, "runtime/api/domain/bar.py")
            _seed_planned_claim(conn, item_id=8240, actor_id=actor,
                                target_ids=[t1, t2])
        finally:
            conn.close()
        outcome = gates.handle_spec_coverage(
            _envelope("advance.preflight.spec_coverage", item_id=8240)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["is_blocked"] is False
        assert outcome.result_payload["missing_paths"] == []
        gates.SpecCoverageEvalResponse(**outcome.result_payload)

    def test_block_when_budget_path_uncovered(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=8241, source=str(actor), spec=self._budget_spec)
            pid = _project_id(conn, 8241)
            t1 = _seed_target(conn, pid, "runtime/api/domain/foo.py")
            _seed_planned_claim(conn, item_id=8241, actor_id=actor,
                                target_ids=[t1])
        finally:
            conn.close()
        outcome = gates.handle_spec_coverage(
            _envelope("advance.preflight.spec_coverage", item_id=8241)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["is_blocked"] is True
        assert outcome.result_payload["missing_paths"] == [
            "runtime/api/domain/bar.py"
        ]
