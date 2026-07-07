"""Self-only target resolution tests for the dispatcher (relay contract).

Split out of :mod:`test_yoke_function_dispatch_claims` for the
authored-file line cap. Covers the item / epic_task shaped ``self_only``
release targets the relay cutover introduced: the dispatcher resolves
the calling session's own active claim server-side and the lookup
itself is the self-ownership proof.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_contracts.api.function_call import (
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import register
from yoke_core.domain.yoke_function_dispatch import dispatch
from runtime.api.domain.test_yoke_function_dispatch_claims import (
    _ClaimMatrixSuite,
    _Req,
    _Resp,
    _make_request,
    _ok_handler,
    _stable_kwargs,
)


class TestSelfOnlyTargetResolution(_ClaimMatrixSuite):
    """Relay contract: self_only release envelopes may ship item /
    epic_task shaped targets; the dispatcher resolves the calling
    session's own active claim onto ``target.claim_id``."""

    def test_item_target_resolves_session_claim(self):
        register(
            "selfitem.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["item", "claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module, "_session_claim_id_for_target", return_value=77,
        ):
            resp = dispatch(_make_request(
                "selfitem.family.op", kind="item", item_id=42,
            ))
        self.assertTrue(resp.success)

    def test_item_target_without_claim_fails(self):
        register(
            "selfitem2.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["item", "claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module, "_session_claim_id_for_target", return_value=None,
        ):
            resp = dispatch(_make_request(
                "selfitem2.family.op", kind="item", item_id=42,
            ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_epic_task_target_resolves_session_claim(self):
        register(
            "selfepic.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["epic_task", "claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module, "_session_claim_id_for_target", return_value=88,
        ):
            resp = dispatch(_make_request(
                "selfepic.family.op",
                kind="epic_task", item_id=0, epic_id=1872, task_num=20,
            ))
        self.assertTrue(resp.success)


class TestSessionClaimIdForTarget(unittest.TestCase):
    """Behavior matrix for the server-side claim lookup itself, against
    an intentional disposable-Postgres selector double (recovers the
    coverage that lived client-side before the relay cutover)."""

    def setUp(self) -> None:
        from runtime.api.fixtures import pg_testdb
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

        name = pg_testdb.create_test_database()
        self.conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name
        )
        apply_fixture_ddl(
            self.conn,
            "CREATE TABLE work_claims (id INTEGER PRIMARY KEY, "
            "session_id TEXT, target_kind TEXT, item_id INTEGER, "
            "epic_id INTEGER, task_num INTEGER, released_at TEXT);",
        )
        from contextlib import contextmanager

        @contextmanager
        def _cm(*_a, **_k):
            yield self.conn

        self._connect = patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        )
        self._connect.start()

    def tearDown(self) -> None:
        self._connect.stop()
        self.conn.close()

    def _seed(self, *, session_id, target_kind, item_id=None, epic_id=None,
              task_num=None, released_at=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, "
            "epic_id, task_num, released_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (session_id, target_kind, item_id, epic_id, task_num, released_at),
        )
        claim_id = int(cur.fetchone()[0])
        self.conn.commit()
        return claim_id

    def test_same_session_scoped(self):
        self._seed(session_id="sid-other", target_kind="epic_task",
                   epic_id=1872, task_num=20)
        target = TargetRef(kind="epic_task", epic_id=1872, task_num=20)
        self.assertIsNone(
            claims_module._session_claim_id_for_target(target, "sid-self")
        )

    def test_released_rows_skipped(self):
        self._seed(session_id="sid-e", target_kind="epic_task",
                   epic_id=1872, task_num=20,
                   released_at="2026-05-27T13:00:00Z")
        target = TargetRef(kind="epic_task", epic_id=1872, task_num=20)
        self.assertIsNone(
            claims_module._session_claim_id_for_target(target, "sid-e")
        )

    def test_epic_task_does_not_match_parent_item_claim(self):
        item_claim = self._seed(
            session_id="sid-e", target_kind="item", item_id=1872,
        )
        task_claim = self._seed(
            session_id="sid-e", target_kind="epic_task",
            epic_id=1872, task_num=20,
        )
        target = TargetRef(kind="epic_task", epic_id=1872, task_num=20)
        resolved = claims_module._session_claim_id_for_target(target, "sid-e")
        self.assertEqual(resolved, task_claim)
        self.assertNotEqual(resolved, item_claim)

    def test_item_target_resolves_latest_active(self):
        claim_id = self._seed(
            session_id="sid-e", target_kind="item", item_id=42,
        )
        target = TargetRef(kind="item", item_id=42)
        self.assertEqual(
            claims_module._session_claim_id_for_target(target, "sid-e"),
            claim_id,
        )

if __name__ == "__main__":
    unittest.main()
