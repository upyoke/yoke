"""Warmup-polling coverage for ``exec_health_check`` (sibling of
:mod:`test_executors`, 350-line cap split).

The health-check stage retries through the container swap window without ever
passing a stale or failed swap — the build assertion still gates every probe.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.tools import executors


class _FakeResponse:
    def __init__(self, status: int, headers: dict | None = None, body: bytes = b"") -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _clock():
    state = {"t": 0.0}
    return (
        lambda: state["t"],
        lambda s: state.__setitem__("t", state["t"] + s),
    )


class ExecHealthCheckWarmupTests(unittest.TestCase):
    def test_default_is_single_shot(self) -> None:
        m = mock.Mock(side_effect=lambda *a, **k: _FakeResponse(503))
        with mock.patch.object(executors.urllib.request, "urlopen", m):
            with redirect_stderr(io.StringIO()):
                rc = executors.exec_health_check("http://x/health")
        self.assertEqual(rc, 1)
        self.assertEqual(m.call_count, 1)

    def test_warmup_retries_through_failures_then_passes(self) -> None:
        responses = iter([
            _FakeResponse(503),
            _FakeResponse(503),
            _FakeResponse(200, body=b'{"build":"newbuild"}'),
        ])
        monotonic, sleep = _clock()
        m = mock.Mock(side_effect=lambda *a, **k: next(responses))
        with mock.patch.object(executors.urllib.request, "urlopen", m), \
                mock.patch.object(executors, "_monotonic", monotonic), \
                mock.patch.object(executors, "_sleep", sleep):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = executors.exec_health_check(
                    "http://x/health", expected_build="newbuild",
                    warmup_timeout=100.0, retry_interval=2.0,
                )
        self.assertEqual(rc, 0)
        self.assertEqual(m.call_count, 3)

    def test_warmup_does_not_pass_a_stale_build(self) -> None:
        # A stale container answering the OLD build during warmup must NOT
        # satisfy the gate — only the NEW build does.
        responses = iter([
            _FakeResponse(200, body=b'{"build":"oldbuild"}'),
            _FakeResponse(200, body=b'{"build":"newbuild"}'),
        ])
        monotonic, sleep = _clock()
        m = mock.Mock(side_effect=lambda *a, **k: next(responses))
        with mock.patch.object(executors.urllib.request, "urlopen", m), \
                mock.patch.object(executors, "_monotonic", monotonic), \
                mock.patch.object(executors, "_sleep", sleep):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = executors.exec_health_check(
                    "http://x/health", expected_build="newbuild",
                    warmup_timeout=100.0, retry_interval=2.0,
                )
        self.assertEqual(rc, 0)
        self.assertEqual(m.call_count, 2)

    def test_warmup_times_out_and_fails_on_persistent_failure(self) -> None:
        monotonic, sleep = _clock()
        m = mock.Mock(side_effect=lambda *a, **k: _FakeResponse(503))
        with mock.patch.object(executors.urllib.request, "urlopen", m), \
                mock.patch.object(executors, "_monotonic", monotonic), \
                mock.patch.object(executors, "_sleep", sleep):
            with redirect_stderr(io.StringIO()):
                rc = executors.exec_health_check(
                    "http://x/health", warmup_timeout=10.0, retry_interval=4.0,
                )
        self.assertEqual(rc, 1)
        # Retried during the window rather than failing on the first probe.
        self.assertGreaterEqual(m.call_count, 2)


if __name__ == "__main__":
    unittest.main()
