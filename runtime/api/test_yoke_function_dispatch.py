"""Direct dispatcher coverage for ``doctor.run.run``.

Sibling to ``test_api_read_functions.py``, which already covers the
read-handler family via direct handler calls. This module exercises
``doctor.run.run`` through the live dispatcher so the registration
metadata, payload validation, scope-required guard, structured
invalid-check error, and machine-payload response are all proven from
the same entrypoint Yoke operators (and the JSON CLI adapter in
``yoke_core.engines.doctor``) actually use.

The scope-required guard is the hotfix protection from
35ef886f3 (require explicit scope flag to prevent silent gh-quota burn);
``invalid_check`` is the bad-slug guard introduced alongside
the corrected DoctorRunRequest shape.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

# Make the worktree's runtime package importable when tests are run
# from a top-level invocation that lacks the repo root on sys.path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.engines.doctor_registry_types import HealthCheck


_SESSION_ID = "test-session-doctor-dispatch"
_FUNCTION_ID = "doctor.run.run"


def _fake_hc_fn(conn, args, rec):
    rec.record("HC-fake", "Fake HC", "PASS", "all good")


def _fake_failing_hc(conn, args, rec):
    rec.record("HC-fail-hc", "Failing HC", "FAIL", "synthetic failure")


class _Conn:
    def execute(self, *_args, **_kwargs):
        return self

    def commit(self):
        pass

    def close(self):
        pass


def _doctor_envelope(**payload):
    return {
        "function": _FUNCTION_ID,
        "actor": {"actor_id": "op", "session_id": _SESSION_ID},
        "target": {"kind": "global"},
        "intent": "test_doctor_run_dispatch",
        "payload": payload,
    }


class TestDoctorRunDispatch(unittest.TestCase):
    """Dispatcher-level coverage for ``doctor.run.run``."""

    @classmethod
    def setUpClass(cls):
        # Idempotent registration: register_all_handlers tolerates being
        # called more than once across the suite.
        register_all_handlers()

    def _dispatch_with_fake_registry(self, hcs, payload):
        # These assert what the engine registry under test contributes, so
        # the runtime is pinned: a local run also collects whatever the
        # calling checkout declares in its own .yoke/doctor/ folder.
        payload = {"runtime": "hosted", "project": "yoke", **payload}
        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS",
            hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=_Conn(),
            ):
                return dispatch(_doctor_envelope(**payload))

    def test_registered_after_register_all_handlers(self):
        # Sanity guard: the dispatcher must resolve the function
        # id without callers reaching for an unregistered direct import.
        from yoke_core.domain.yoke_function_registry import lookup

        entry = lookup(_FUNCTION_ID)
        self.assertIsNotNone(
            entry,
            "doctor.run.run must be registered through "
            "yoke_core.domain.handlers.__init_register__.register_all_handlers",
        )

    def test_scope_required_when_no_scope_supplied(self):
        # Machine callers must explicitly choose a scope. Without
        # quick/full/only the handler rejects rather than silently
        # running the full GitHub-dependent suite.
        result = self._dispatch_with_fake_registry(
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn)],
            payload={"project": "yoke"},
        )
        envelope = result.model_dump()
        self.assertFalse(envelope["success"])
        self.assertEqual(envelope["error"]["code"], "scope_required")

    def test_scope_required_rejects_multiple_scopes(self):
        result = self._dispatch_with_fake_registry(
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn)],
            payload={"quick": True, "full": True},
        )
        envelope = result.model_dump()
        self.assertFalse(envelope["success"])
        self.assertEqual(envelope["error"]["code"], "scope_required")

    def test_invalid_check_for_unknown_slug(self):
        # An unknown slug must produce a structured error, not a
        # successful empty result.
        result = self._dispatch_with_fake_registry(
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn)],
            payload={"only": "HC-this-check-does-not-exist"},
        )
        envelope = result.model_dump()
        self.assertFalse(envelope["success"])
        self.assertEqual(envelope["error"]["code"], "invalid_check")
        self.assertIn(
            "this-check-does-not-exist",
            envelope["error"]["message"],
        )

    def test_known_slug_runs_through_dispatcher(self):
        result = self._dispatch_with_fake_registry(
            [HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn)],
            payload={"only": "fake"},
        )
        envelope = result.model_dump()
        self.assertTrue(envelope["success"])
        payload = envelope["result"]
        self.assertEqual(payload["scope"], "only")
        self.assertEqual(payload["project"], "yoke")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["hc"], "HC-fake")
        self.assertEqual(payload["pass_count"], 1)
        self.assertEqual(payload["fail_count"], 0)

    def test_full_scope_runs_every_hc(self):
        # Two HCs, one passing and one failing; ``full=True`` must run
        # both and surface the failure count.
        result = self._dispatch_with_fake_registry(
            [
                HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn),
                HealthCheck(
                    slug="fail-hc",
                    name="Failing HC",
                    fn=_fake_failing_hc,
                ),
            ],
            payload={"full": True},
        )
        envelope = result.model_dump()
        self.assertTrue(envelope["success"])
        payload = envelope["result"]
        self.assertEqual(payload["scope"], "full")
        self.assertEqual(payload["fail_count"], 1)
        self.assertEqual(payload["pass_count"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
