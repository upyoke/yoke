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
``invalid_check`` is the new AC-3 bad-slug guard introduced alongside
the corrected DoctorRunRequest shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS", hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
            ):
                return dispatch(_doctor_envelope(**payload))

    def test_registered_after_register_all_handlers(self):
        # Sanity guard for AC-1: the dispatcher must resolve the function
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
                    slug="fail-hc", name="Failing HC", fn=_fake_failing_hc,
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


_CLI_MODULE = "yoke_core.domain.yoke_function_dispatch_cli"


def _run_cli(envelope_bytes, *, use_stdin=False, extra_args=()):
    """Invoke the CLI module as a subprocess and return the completed proc."""
    args = [sys.executable, "-m", _CLI_MODULE]
    if use_stdin:
        args.append("--stdin")
        stdin_payload = envelope_bytes
        path_to_clean = None
    else:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".json", delete=False,
        ) as fh:
            fh.write(envelope_bytes)
            envelope_path = fh.name
        args.extend(["--request-file", envelope_path])
        stdin_payload = None
        path_to_clean = envelope_path
    args.extend(extra_args)
    try:
        from yoke_core.domain import db_backend

        def _invoke():
            env = {**os.environ}
            env.pop("YOKE_DB", None)
            return subprocess.run(
                args,
                input=stdin_payload,
                capture_output=True,
                timeout=60,
                env=env,
            )

        if db_backend.is_postgres():
            from runtime.api.fixtures.pg_testdb import test_database

            with test_database():
                return _invoke()
        return _invoke()
    finally:
        if path_to_clean is not None:
            try:
                os.unlink(path_to_clean)
            except OSError:
                pass


class TestYokeFunctionDispatchCli(unittest.TestCase):
    """Subprocess-level coverage for the CLI exit-code contract."""

    @classmethod
    def setUpClass(cls):
        register_all_handlers()

    def test_envelope_invalid_exits_two_with_field_path(self):
        # Malformed envelope (missing actor.session_id) must exit 2
        # and surface the offending field path on stderr. ``actor.actor_id``
        # is optional (server-resolved from ``session_id``); only
        # ``session_id`` is required at the envelope boundary.
        envelope = {
            "function": "items.get.run",
            "actor": {"actor_id": "op-only"},
            "target": {"kind": "item", "item_id": 1},
            "payload": {"fields": ["title"]},
        }
        proc = _run_cli(json.dumps(envelope).encode("utf-8"))
        self.assertEqual(proc.returncode, 2, proc.stderr.decode("utf-8"))
        stderr = proc.stderr.decode("utf-8")
        self.assertIn("session_id", stderr)

    def test_invalid_json_exits_two(self):
        # Input-parse failure shares the exit-2 envelope-invalid path.
        proc = _run_cli(b"{this is not json", use_stdin=True)
        self.assertEqual(proc.returncode, 2, proc.stderr.decode("utf-8"))
        stderr = proc.stderr.decode("utf-8")
        self.assertIn("invalid JSON", stderr)

    def test_unknown_function_id_exits_one(self):
        # Envelope constructs cleanly but dispatch fails -- unknown
        # function id is the simplest such case.
        envelope = {
            "function": "definitely.not.a.real.function",
            "actor": {"actor_id": "op", "session_id": "cli-test"},
            "target": {"kind": "global"},
            "payload": {},
        }
        proc = _run_cli(json.dumps(envelope).encode("utf-8"))
        self.assertEqual(proc.returncode, 1, proc.stderr.decode("utf-8"))
        stderr = proc.stderr.decode("utf-8")
        self.assertIn("function_not_registered", stderr)
        # Second stderr line carries the full response JSON for inspection.
        last_json_line = stderr.strip().splitlines()[-1]
        decoded = json.loads(last_json_line)
        self.assertFalse(decoded["success"])
        self.assertEqual(decoded["error"]["code"], "function_not_registered")

    def test_valid_envelope_exits_zero_with_response_json(self):
        # A valid envelope to a registered read function exits 0 and
        # writes a parseable FunctionCallResponse to stdout.
        envelope = {
            "function": "items.get.run",
            "actor": {"actor_id": "op", "session_id": "cli-test"},
            "target": {"kind": "item", "item_id": 1},
            "payload": {"fields": ["title"]},
        }
        proc = _run_cli(json.dumps(envelope).encode("utf-8"))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        stdout = proc.stdout.decode("utf-8").strip()
        decoded = json.loads(stdout)
        self.assertTrue(decoded["success"])
        self.assertEqual(decoded["function"], "items.get.run")
        self.assertIn("title", decoded["result"]["fields"])

    def test_stdin_input_path_matches_file_path(self):
        envelope = {
            "function": "items.get.run",
            "actor": {"actor_id": "op", "session_id": "cli-test"},
            "target": {"kind": "item", "item_id": 1},
            "payload": {"fields": ["title"]},
        }
        proc = _run_cli(json.dumps(envelope).encode("utf-8"), use_stdin=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        decoded = json.loads(proc.stdout.decode("utf-8").strip())
        self.assertTrue(decoded["success"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
