"""Tests for yoke_core.domain.conduct_reviewed_handoff."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.domain import conduct_reviewed_handoff as mod
from yoke_core.domain.sessions_lifecycle_release_failure import (
    RELEASE_FAILURE_ALREADY_TERMINAL,
    RELEASE_FAILURE_ITEM_NOT_FOUND,
)
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — fixture re-export
)

TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"


class TestNormalizeId(unittest.TestCase):
    def test_sun_prefix(self) -> None:
        self.assertEqual(mod._normalize_item_id(TEST_EPIC_REF), TEST_EPIC_ID)

    def test_zero_padded(self) -> None:
        self.assertEqual(mod._normalize_item_id("007"), 7)

    def test_invalid(self) -> None:
        self.assertIsNone(mod._normalize_item_id("nope"))


class TestRun(unittest.TestCase):
    def _run_capture(self, epic_id: int) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = mod.run(epic_id)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_wrong_pre_status_exits_1(self) -> None:
        with mock.patch.object(mod, "_fetch_status", return_value="implementing"):
            rc, _, err = self._run_capture(42)
        self.assertEqual(rc, 1)
        self.assertIn("expected 'reviewing-implementation'", err)

    def test_missing_item_exits_1(self) -> None:
        with mock.patch.object(mod, "_fetch_status", return_value=None):
            rc, _, err = self._run_capture(42)
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_simulation_gate_failure_exits_2(self) -> None:
        with mock.patch.object(
            mod,
            "_fetch_status",
            return_value="reviewing-implementation",
        ), mock.patch.object(mod, "_run_simulation_gate", return_value=1):
            rc, _, err = self._run_capture(42)
        self.assertEqual(rc, 2)
        self.assertIn("Simulation gate failed", err)

    def test_status_write_failure_exits_3(self) -> None:
        with mock.patch.object(
            mod,
            "_fetch_status",
            side_effect=["reviewing-implementation"],
        ), mock.patch.object(
            mod, "_run_simulation_gate", return_value=0
        ), mock.patch.object(
            mod, "_run_status_write", return_value=(1, "write failed details")
        ):
            rc, _, err = self._run_capture(42)
        self.assertEqual(rc, 3)
        self.assertIn("Status write failed", err)
        self.assertIn("write failed details", err)

    def test_post_write_verification_failure_exits_3(self) -> None:
        statuses = iter(["reviewing-implementation", "reviewing-implementation"])
        with mock.patch.object(
            mod, "_fetch_status", side_effect=lambda _id: next(statuses)
        ), mock.patch.object(
            mod, "_run_simulation_gate", return_value=0
        ), mock.patch.object(
            mod, "_run_status_write", return_value=(0, "")
        ):
            rc, _, err = self._run_capture(42)
        self.assertEqual(rc, 3)
        self.assertIn("Post-write verification failed", err)

    def test_success_path(self) -> None:
        statuses = iter(["reviewing-implementation", "reviewed-implementation"])
        with mock.patch.object(
            mod, "_fetch_status", side_effect=lambda _id: next(statuses)
        ), mock.patch.object(
            mod, "_run_simulation_gate", return_value=0
        ), mock.patch.object(
            mod, "_run_status_write", return_value=(0, "")
        ), mock.patch.object(
            mod, "_release_conduct_claim", return_value={"released": True}
        ):
            rc, out, _ = self._run_capture(42)
        self.assertEqual(rc, 0)
        self.assertIn("reviewing-implementation → reviewed-implementation", out)


class TestSimulationGateBypass(unittest.TestCase):
    def test_skip_env_var_bypasses(self) -> None:
        err_buf = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"YOKE_SKIP_SIMULATION": "1"},
            clear=False,
        ), redirect_stderr(err_buf):
            rc = mod._run_simulation_gate(42)
        self.assertEqual(rc, 0)
        self.assertIn("bypassed via YOKE_SKIP_SIMULATION", err_buf.getvalue())


class TestMain(unittest.TestCase):
    def test_invalid_id(self) -> None:
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc = mod.main(["not-an-id"])
        self.assertEqual(rc, 1)
        self.assertIn("invalid epic ID", err_buf.getvalue())

    def test_forwards_to_run(self) -> None:
        with mock.patch.object(mod, "run", return_value=0) as run_mock:
            rc = mod.main([TEST_EPIC_REF])
        self.assertEqual(rc, 0)
        run_mock.assert_called_once_with(TEST_EPIC_ID, session_id=None)

    def test_forwards_explicit_session_id(self) -> None:
        with mock.patch.object(mod, "run", return_value=0) as run_mock:
            rc = mod.main(["--session-id", "sess-1", TEST_EPIC_REF])
        self.assertEqual(rc, 0)
        run_mock.assert_called_once_with(TEST_EPIC_ID, session_id="sess-1")


class TestAutoClaimRelease(unittest.TestCase):
    """T-4: successful handoff auto-releases the Conduct item claim."""

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", side_effect=["reviewing-implementation", "reviewed-implementation"])
    @mock.patch.object(mod, "_run_simulation_gate", return_value=0)
    @mock.patch.object(mod, "_run_status_write", return_value=(0, ""))
    def test_success_calls_release(self, _write, _gate, _fetch, release_mock) -> None:
        release_mock.return_value = {"released": True}
        rc = mod.run(42, session_id="sess-1")
        self.assertEqual(rc, 0)
        release_mock.assert_called_once_with(42, session_id="sess-1")

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", return_value="implementing")
    def test_precondition_failure_skips_release(self, _fetch, release_mock) -> None:
        rc = mod.run(42)
        self.assertEqual(rc, 1)
        release_mock.assert_not_called()

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", side_effect=["reviewing-implementation", "reviewing-implementation"])
    @mock.patch.object(mod, "_run_simulation_gate", return_value=0)
    @mock.patch.object(mod, "_run_status_write", return_value=(0, ""))
    def test_post_write_verification_failure_skips_release(self, _write, _gate, _fetch, release_mock) -> None:
        rc = mod.run(42)
        self.assertEqual(rc, 3)
        release_mock.assert_not_called()

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", side_effect=["reviewing-implementation", "reviewed-implementation"])
    @mock.patch.object(mod, "_run_simulation_gate", return_value=0)
    @mock.patch.object(mod, "_run_status_write", return_value=(0, ""))
    def test_missing_claim_is_idempotent_success(self, _write, _gate, _fetch, release_mock) -> None:
        release_mock.return_value = {
            "released": False,
            "failure_reason": RELEASE_FAILURE_ITEM_NOT_FOUND,
        }
        rc = mod.run(42)
        self.assertEqual(rc, 0)

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", side_effect=["reviewing-implementation", "reviewed-implementation"])
    @mock.patch.object(mod, "_run_simulation_gate", return_value=0)
    @mock.patch.object(mod, "_run_status_write", return_value=(0, ""))
    def test_already_terminal_claim_is_idempotent_success(self, _write, _gate, _fetch, release_mock) -> None:
        release_mock.return_value = {
            "released": False,
            "failure_reason": RELEASE_FAILURE_ALREADY_TERMINAL,
        }
        rc = mod.run(42)
        self.assertEqual(rc, 0)

    @mock.patch.object(mod, "_release_conduct_claim")
    @mock.patch.object(mod, "_fetch_status", side_effect=["reviewing-implementation", "reviewed-implementation"])
    @mock.patch.object(mod, "_run_simulation_gate", return_value=0)
    @mock.patch.object(mod, "_run_status_write", return_value=(0, ""))
    def test_claim_release_failure_exits_4(self, _write, _gate, _fetch, release_mock) -> None:
        release_mock.return_value = {"released": False, "reason": "missing_session_id"}
        rc = mod.run(42)
        self.assertEqual(rc, 4)

def test_run_status_write_exercises_real_backlog_update(tmp_db):
    _seed_item(
        tmp_db,
        id=43,
        type="epic",
        status="reviewing-implementation",
        project="yoke",
    )

    with _patch_externals(), \
         mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}, clear=False):
        rc, output = mod._run_status_write(43)

    assert rc == 0
    assert "reviewed-implementation" in output
    assert _item_field(tmp_db, 43, "status") == "reviewed-implementation"


if __name__ == "__main__":
    unittest.main()
