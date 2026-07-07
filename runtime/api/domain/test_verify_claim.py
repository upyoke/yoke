"""Tests for yoke_core.domain.verify_claim."""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from yoke_core.domain import verify_claim as mod

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestNormalizeId(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(mod._normalize_item_id(TEST_ITEM_REF), TEST_ITEM_ID)
        self.assertEqual(mod._normalize_item_id("007"), 7)
        self.assertEqual(mod._normalize_item_id(str(TEST_ITEM_ID)), TEST_ITEM_ID)

    def test_invalid(self) -> None:
        self.assertIsNone(mod._normalize_item_id(""))
        self.assertIsNone(mod._normalize_item_id("abc"))


class TestSessionAndBypass(unittest.TestCase):
    def test_resolve_session_id_prefers_yoke(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "YOKE_SESSION_ID": "sid-yoke",
                "CLAUDE_SESSION_ID": "sid-claude",
                "CODEX_THREAD_ID": "sid-codex",
            },
            clear=False,
        ):
            self.assertEqual(mod._resolve_session_id(), "sid-yoke")

    def test_resolve_session_id_claude_next(self) -> None:
        env = {
            "YOKE_SESSION_ID": "",
            "CLAUDE_SESSION_ID": "sid-claude",
            "CODEX_THREAD_ID": "sid-codex",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(mod._resolve_session_id(), "sid-claude")

    def test_resolve_bypass_direct(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"YOKE_CLAIM_BYPASS": "cascade:YOK-1"},
            clear=False,
        ):
            self.assertEqual(mod._resolve_bypass(), "cascade:YOK-1")

    def test_resolve_bypass_repair_status(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "YOKE_CLAIM_BYPASS": "",
                "YOKE_STATUS_SOURCE": "repair-status:incident-42",
            },
            clear=False,
        ):
            self.assertEqual(mod._resolve_bypass(), "repair-status:incident-42")

    def test_resolve_bypass_empty(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"YOKE_CLAIM_BYPASS": "", "YOKE_STATUS_SOURCE": ""},
            clear=False,
        ):
            self.assertEqual(mod._resolve_bypass(), "")


class TestVerify(unittest.TestCase):
    def test_bypass_path_returns_verified(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value="sid-a"), \
             mock.patch.object(mod, "_resolve_bypass", return_value="cascade:YOK-1"), \
             mock.patch.object(mod, "_emit_lifecycle_event") as emit_mock:
            code, payload = mod.verify(42)
        self.assertEqual(code, 0)
        self.assertTrue(payload["verified"])
        self.assertTrue(payload["bypassed"])
        self.assertEqual(payload["claimant"], "bypass")
        self.assertEqual(emit_mock.call_args[0][0], "ClaimVerificationBypassed")

    def test_no_session_denies(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value=""), \
             mock.patch.object(mod, "_resolve_bypass", return_value=""), \
             mock.patch.object(mod, "_emit_lifecycle_event") as emit_mock:
            code, payload = mod.verify(42)
        self.assertEqual(code, 1)
        self.assertFalse(payload["verified"])
        # Reframed denial: infrastructure-gap signal, no env-var teaching.
        self.assertIn("infrastructure gap", payload["reason"])
        self.assertNotIn("YOKE_SESSION_ID", payload["reason"])
        self.assertEqual(emit_mock.call_args[0][0], "ClaimVerificationDenied")

    def test_degraded_db_allows(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value="sid-a"), \
             mock.patch.object(mod, "_resolve_bypass", return_value=""), \
             mock.patch.object(mod, "_db_available", return_value=False):
            code, payload = mod.verify(42)
        self.assertEqual(code, 0)
        self.assertTrue(payload["verified"])
        self.assertTrue(payload["bypassed"])
        self.assertEqual(payload["claimant"], "degraded")

    def test_no_active_claim_denies(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value="sid-a"), \
             mock.patch.object(mod, "_resolve_bypass", return_value=""), \
             mock.patch.object(mod, "_db_available", return_value=True), \
             mock.patch.object(mod, "_fetch_claim", return_value=None), \
             mock.patch.object(mod, "_emit_lifecycle_event"):
            code, payload = mod.verify(42)
        self.assertEqual(code, 1)
        self.assertFalse(payload["verified"])
        self.assertIn("no active claim", payload["reason"])

    def test_matching_claim_verifies(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value="sid-a"), \
             mock.patch.object(mod, "_resolve_bypass", return_value=""), \
             mock.patch.object(mod, "_db_available", return_value=True), \
             mock.patch.object(
                mod,
                "_fetch_claim",
                return_value={
                    "id": 1,
                    "session_id": "sid-a",
                    "item_id": "42",
                    "claim_type": "exclusive",
                    "claimed_at": "ts",
                },
            ) as fetch_mock:
            code, payload = mod.verify(42)
        self.assertEqual(code, 0)
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["claimant"], "sid-a")
        # _fetch_claim should be called with the integer id (not YOK-N)
        fetch_mock.assert_called_once_with(42)

    def test_wrong_session_denies(self) -> None:
        with mock.patch.object(mod, "_resolve_session_id", return_value="sid-a"), \
             mock.patch.object(mod, "_resolve_bypass", return_value=""), \
             mock.patch.object(mod, "_db_available", return_value=True), \
             mock.patch.object(
                mod,
                "_fetch_claim",
                return_value={
                    "id": 1,
                    "session_id": "sid-b",
                    "item_id": TEST_ITEM_REF,
                    "claim_type": "exclusive",
                    "claimed_at": "ts",
                },
            ), mock.patch.object(mod, "_emit_lifecycle_event"):
            code, payload = mod.verify(42)
        self.assertEqual(code, 1)
        self.assertIn("different session", payload["reason"])
        self.assertEqual(payload["claimant"], "sid-b")


_WORK_CLAIMS_DDL = (
    "CREATE TABLE work_claims ("
    "id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT, "
    "item_id INTEGER, claim_type TEXT, claimed_at TEXT, "
    "released_at TEXT)"
)


def _placeholder(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_work_claims_schema() -> None:
    """``apply_schema`` strategy for the verifier's minimal work_claims DDL.

    Resolves its connection through the backend factory so the same DDL builds
    on SQLite and Postgres; ``_fetch_claim`` reads the same backend-resolved DB.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute(
                _WORK_CLAIMS_DDL.replace(
                    "id INTEGER PRIMARY KEY",
                    "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                )
            )
        else:
            conn.execute(_WORK_CLAIMS_DDL)
        conn.commit()
    finally:
        conn.close()


class TestFetchClaimIdForms(unittest.TestCase):
    """Ensure _fetch_claim resolves item-target claims by integer item id.

    The legacy YOK-N text-id form was retired with the typed-target cutover;
    item claims now store the bare integer in ``item_id`` with
    ``target_kind='item'``, so the YOK-N → item lookup pair query path
    is no longer exercised here.
    """

    def test_bare_int_item_id_found(self) -> None:
        import tempfile

        from runtime.api.fixtures.file_test_db import (
            connect_test_db,
            init_test_db,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with init_test_db(
                Path(tmpdir), apply_schema=_apply_work_claims_schema
            ) as db_path:
                seed = connect_test_db(db_path)
                p = _placeholder(seed)
                seed.execute(
                    "INSERT INTO work_claims "
                    "(session_id, target_kind, item_id, claim_type, claimed_at) "
                    f"VALUES ({p}, 'item', {p}, {p}, {p})",
                    ("sid-a", 42, "exclusive", "2026-01-01T00:00:00Z"),
                )
                seed.commit()
                seed.close()
                with mock.patch.dict(
                    os.environ, {"YOKE_DB": db_path}, clear=False
                ):
                    claim = mod._fetch_claim(42)
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim["session_id"], "sid-a")
        self.assertEqual(claim["item_id"], 42)

    def test_released_claim_not_returned(self) -> None:
        import tempfile

        from runtime.api.fixtures.file_test_db import (
            connect_test_db,
            init_test_db,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with init_test_db(
                Path(tmpdir), apply_schema=_apply_work_claims_schema
            ) as db_path:
                seed = connect_test_db(db_path)
                p = _placeholder(seed)
                seed.execute(
                    "INSERT INTO work_claims "
                    "(session_id, target_kind, item_id, claim_type, "
                    "claimed_at, released_at) "
                    f"VALUES ({p}, 'item', {p}, {p}, {p}, {p})",
                    ("sid-a", 42, "exclusive",
                     "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
                )
                seed.commit()
                seed.close()
                with mock.patch.dict(
                    os.environ, {"YOKE_DB": db_path}, clear=False
                ):
                    claim = mod._fetch_claim(42)
        self.assertIsNone(claim)


class TestMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = mod.main(argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_invalid_id_exits_2(self) -> None:
        rc, _, err = self._run(["--item-id", ""])
        self.assertEqual(rc, 2)
        self.assertIn("invalid --item-id", err)

    def test_emits_json_envelope(self) -> None:
        with mock.patch.object(
            mod,
            "verify",
            return_value=(
                0,
                {
                    "verified": True,
                    "session_id": "sid",
                    "claimant": "sid",
                    "reason": "ok",
                    "bypassed": False,
                },
            ),
        ):
            rc, out, _ = self._run(["--item-id", TEST_ITEM_REF])
        self.assertEqual(rc, 0)
        payload = json.loads(out.strip())
        self.assertTrue(payload["verified"])


if __name__ == "__main__":
    unittest.main()
