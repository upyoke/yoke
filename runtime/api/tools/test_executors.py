"""Tests for :mod:`yoke_core.tools.executors`.

These tests replace the semantic coverage previously provided by the
shell-level ``test-executors.sh`` harness for the lane-F-owned
executors.  They exercise each Python executor in isolation
without touching the deployment pipeline or any external network.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.tools import executors


class ExecAutoTests(unittest.TestCase):
    def test_returns_zero_and_prints_log(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = executors.exec_auto()
        self.assertEqual(rc, 0)
        self.assertIn("exec-auto: stage complete", buf.getvalue())


class _FakeResponse:
    def __init__(
        self,
        status: int,
        headers: dict | None = None,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body

    def getcode(self) -> int:  # pragma: no cover -- only used when .status absent
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _sent_headers(urlopen_mock: mock.MagicMock) -> dict:
    """Lower-cased headers carried by the request handed to ``urlopen``."""
    request = urlopen_mock.call_args[0][0]
    if isinstance(request, executors.urllib.request.Request):
        return {k.lower(): v for k, v in request.header_items()}
    return {}


class ExecHealthCheckTests(unittest.TestCase):
    def test_returns_zero_on_2xx(self) -> None:
        fake = _FakeResponse(204)
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check("http://example.invalid/health")
        self.assertEqual(rc, 0)
        self.assertIn("204", buf.getvalue())

    def test_returns_one_on_non_2xx(self) -> None:
        fake = _FakeResponse(500)
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check("http://example.invalid/health")
        self.assertEqual(rc, 1)
        self.assertIn("failed health check", buf.getvalue())

    def test_returns_one_on_connection_error(self) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("no route")

        with mock.patch.object(executors.urllib.request, "urlopen", side_effect=_raise):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check("http://example.invalid/health")
        self.assertEqual(rc, 1)
        self.assertIn("no route", buf.getvalue())

    def test_rejects_empty_url(self) -> None:
        rc = executors.exec_health_check("")
        self.assertEqual(rc, 1)

    def test_request_id_sent_and_echoed_returns_zero(self) -> None:
        fake = _FakeResponse(200, headers={"x-request-id": "rid-1"})
        with mock.patch.object(
            executors.urllib.request, "urlopen", return_value=fake
        ) as m:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health", request_id="rid-1"
                )
        self.assertEqual(rc, 0)
        self.assertIn("echoed", buf.getvalue())
        self.assertEqual(_sent_headers(m).get("x-request-id"), "rid-1")

    def test_request_id_missing_echo_returns_one(self) -> None:
        fake = _FakeResponse(200, headers={})
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health", request_id="rid-2"
                )
        self.assertEqual(rc, 1)
        self.assertIn("not echo x-request-id", buf.getvalue())
        self.assertIn("propagation contract violated", buf.getvalue())

    def test_request_id_mismatched_echo_returns_one(self) -> None:
        fake = _FakeResponse(200, headers={"x-request-id": "other"})
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health", request_id="rid-3"
                )
        self.assertEqual(rc, 1)
        self.assertIn("got 'other'", buf.getvalue())
        self.assertIn("propagation contract violated", buf.getvalue())

    def test_no_request_id_sends_no_header(self) -> None:
        fake = _FakeResponse(204)
        with mock.patch.object(
            executors.urllib.request, "urlopen", return_value=fake
        ) as m:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check("http://example.invalid/health")
        self.assertEqual(rc, 0)
        self.assertNotIn("x-request-id", _sent_headers(m))

    def test_expected_build_match_returns_zero(self) -> None:
        fake = _FakeResponse(
            200, body=b'{"status":"ok","version":"v1","build":"abc123def456"}'
        )
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    expected_build="abc123def456",
                )
        self.assertEqual(rc, 0)
        self.assertIn("build abc123def456 confirmed", buf.getvalue())

    def test_expected_build_mismatch_returns_one(self) -> None:
        fake = _FakeResponse(
            200, body=b'{"status":"ok","version":"v1","build":"stale000"}'
        )
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    expected_build="abc123def456",
                )
        self.assertEqual(rc, 1)
        self.assertIn("serves build 'stale000'", buf.getvalue())
        self.assertIn("not running the deployed code", buf.getvalue())

    def test_expected_build_unparseable_body_returns_one(self) -> None:
        fake = _FakeResponse(200, body=b"not json")
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    expected_build="abc123def456",
                )
        self.assertEqual(rc, 1)
        self.assertIn("serves build ''", buf.getvalue())

    def test_schema_ready_true_returns_zero(self) -> None:
        fake = _FakeResponse(
            200,
            body=b'{"status":"ok","schema_ready":true,"schema_missing_tables":[]}',
        )
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    require_schema_ready=True,
                )
        self.assertEqual(rc, 0)
        self.assertIn("schema ready", buf.getvalue())

    def test_schema_ready_false_names_missing_tables_and_returns_one(self) -> None:
        fake = _FakeResponse(
            200,
            body=(
                b'{"status":"ok","schema_ready":false,'
                b'"schema_missing_tables":["strategy_docs"]}'
            ),
        )
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    require_schema_ready=True,
                )
        self.assertEqual(rc, 1)
        self.assertIn("schema_ready=true", buf.getvalue())
        self.assertIn("missing tables: strategy_docs", buf.getvalue())

    def test_schema_ready_absent_from_payload_returns_one(self) -> None:
        fake = _FakeResponse(200, body=b'{"status":"ok","version":"v1"}')
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    require_schema_ready=True,
                )
        self.assertEqual(rc, 1)
        self.assertIn("does not report schema_ready=true", buf.getvalue())

    def test_schema_ready_and_build_assert_against_one_body_read(self) -> None:
        fake = _FakeResponse(
            200,
            body=(
                b'{"status":"ok","version":"v1","build":"abc123def456",'
                b'"schema_ready":true,"schema_missing_tables":[]}'
            ),
        )
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check(
                    "http://example.invalid/health",
                    expected_build="abc123def456",
                    require_schema_ready=True,
                )
        self.assertEqual(rc, 0)
        self.assertIn("build abc123def456 confirmed", buf.getvalue())
        self.assertIn("schema ready", buf.getvalue())

    def test_without_require_schema_ready_not_ready_payload_passes(self) -> None:
        fake = _FakeResponse(200, body=b'{"status":"ok","schema_ready":false}')
        with mock.patch.object(executors.urllib.request, "urlopen", return_value=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_health_check("http://example.invalid/health")
        self.assertEqual(rc, 0)


class MainCLITests(unittest.TestCase):
    def test_auto_dispatch(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = executors.main(["auto"])
        self.assertEqual(rc, 0)
        self.assertIn("exec-auto", buf.getvalue())

    def test_health_check_dispatch(self) -> None:
        with mock.patch.object(executors, "exec_health_check", return_value=0) as m:
            rc = executors.main(["health-check", "http://x/"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("http://x/", request_id="")

    def test_health_check_dispatch_with_request_id(self) -> None:
        with mock.patch.object(executors, "exec_health_check", return_value=0) as m:
            rc = executors.main(["health-check", "http://x/", "rid-9"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("http://x/", request_id="rid-9")

    def test_ephemeral_verify_dispatch(self) -> None:
        with mock.patch.object(executors, "exec_ephemeral_verify", return_value=0) as m:
            rc = executors.main(
                [
                    "ephemeral-verify", "buzz", "org/repo", "br", "wf.yml",
                    "d.example", "abc",
                ]
            )
        self.assertEqual(rc, 0)
        m.assert_called_once_with(
            "org/repo", "br", "wf.yml", "d.example", "abc",
            project="buzz",
        )

    def test_unknown_command(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = executors.main(["nonsense"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown executor", buf.getvalue())

    def test_empty_argv(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = executors.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
