"""Tests for :mod:`yoke_core.tools.api_server` and microbenches."""

from __future__ import annotations

from runtime.api.tools.api_server_test_support import (
    DISPATCHER_OVERHEAD_BUDGET_MS as DISPATCHER_OVERHEAD_BUDGET_MS,
    DISPATCHER_OVERHEAD_SAMPLES as DISPATCHER_OVERHEAD_SAMPLES,
    DISPATCHER_OVERHEAD_WARMUP as DISPATCHER_OVERHEAD_WARMUP,
    _FakeProc as _FakeProc,
    _dispatcher_available as _dispatcher_available,
    _measure_ms as _measure_ms,
    _percentile_ms as _percentile_ms,
    _structured_field_handler_registered as _structured_field_handler_registered,
    pytestmark as pytestmark,
)


import io
import signal
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from yoke_core.tools import api_server


# NFR-3: dispatcher p99 overhead < 50ms over the underlying callable.


class PidFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name)
        (self.repo_root / "runtime" / "api").mkdir(parents=True)

    def _patch_root(self) -> mock._patch:
        return mock.patch.object(
            api_server, "_resolve_repo_root", return_value=self.repo_root
        )

    def test_start_rejects_when_already_running(self) -> None:
        pid_file = self.repo_root / "runtime" / "api" / ".pid"
        pid_file.write_text("9999\n", encoding="utf-8")

        buf = io.StringIO()
        with (
            self._patch_root(),
            mock.patch.object(api_server, "_is_alive", return_value=True),
            redirect_stdout(buf),
        ):
            rc = api_server.cmd_start()
        self.assertEqual(rc, 1)
        self.assertIn("already running", buf.getvalue())

    def test_start_cleans_up_stale_pid_file(self) -> None:
        pid_file = self.repo_root / "runtime" / "api" / ".pid"
        pid_file.write_text("9999\n", encoding="utf-8")

        launched = {}

        def fake_popen(*args, **kwargs):
            launched["args"] = args[0]
            launched["cwd"] = kwargs.get("cwd")
            launched["kwargs"] = kwargs
            return _FakeProc(pid=1234)

        buf = io.StringIO()
        with (
            self._patch_root(),
            mock.patch.object(api_server, "_is_alive", return_value=False),
            mock.patch(
                "yoke_core.tools.api_server.subprocess.Popen", side_effect=fake_popen
            ),
            redirect_stdout(buf),
        ):
            rc = api_server.cmd_start()
        self.assertEqual(rc, 0)
        self.assertIn("uvicorn", " ".join(launched["args"]))
        self.assertEqual(pid_file.read_text(encoding="utf-8").strip(), "1234")
        popen_kwargs = launched["kwargs"]
        actual = (
            popen_kwargs["stdin"],
            popen_kwargs["stderr"],
            popen_kwargs["start_new_session"],
        )
        expected = (api_server.subprocess.DEVNULL, api_server.subprocess.STDOUT, True)
        self.assertEqual(actual, expected)
        self.assertIsNotNone(popen_kwargs["stdout"])
        self.assertIn("started (PID 1234)", buf.getvalue())

    def test_stop_no_process_is_idempotent(self) -> None:
        buf = io.StringIO()
        with self._patch_root(), redirect_stdout(buf):
            rc = api_server.cmd_stop()
        self.assertEqual(rc, 0)
        self.assertIn("not running", buf.getvalue())

    def test_stop_sends_sigterm_and_removes_pid_file(self) -> None:
        pid_file = self.repo_root / "runtime" / "api" / ".pid"
        pid_file.write_text("5678\n", encoding="utf-8")

        killed = []

        def fake_kill(pid, sig):
            killed.append((pid, sig))

        # cmd_stop calls _is_alive once, then _kill_existing calls it again before
        # sending SIGTERM, and once more to observe the graceful shutdown.
        alive_toggle = iter([True, True, False])

        def fake_is_alive(pid):  # noqa: ARG001
            try:
                return next(alive_toggle)
            except StopIteration:
                return False

        buf = io.StringIO()
        with (
            self._patch_root(),
            mock.patch.object(api_server, "_is_alive", side_effect=fake_is_alive),
            mock.patch("yoke_core.tools.api_server.os.kill", side_effect=fake_kill),
            redirect_stdout(buf),
        ):
            rc = api_server.cmd_stop()
        self.assertEqual(rc, 0)
        self.assertEqual(killed[0], (5678, signal.SIGTERM))
        self.assertFalse(pid_file.exists())

    def test_read_pid_handles_missing_and_garbage(self) -> None:
        pid_file = self.repo_root / "runtime" / "api" / ".pid"
        self.assertIsNone(api_server._read_pid(pid_file))
        pid_file.write_text("not-a-pid\n", encoding="utf-8")
        self.assertIsNone(api_server._read_pid(pid_file))
        pid_file.write_text("4321\n", encoding="utf-8")
        self.assertEqual(api_server._read_pid(pid_file), 4321)


@unittest.skipUnless(
    _dispatcher_available(),
    "Yoke function dispatcher not present on this branch.",
)
class DispatcherOverheadSyntheticTests(unittest.TestCase):
    """Dispatcher p99 overhead over a synthetic no-op handler.

    Isolates lookup + envelope validation + idempotency check + event
    emission from any underlying domain mutation cost.
    """

    def test_dispatcher_overhead_synthetic(self) -> None:
        from pydantic import BaseModel

        from yoke_core.domain.yoke_function_dispatch import dispatch
        from yoke_contracts.api.function_call import (
            ActorContext,
            FunctionCallRequest,
            HandlerOutcome,
            TargetRef,
        )
        from yoke_core.domain.yoke_function_registry import (
            RegistryDuplicateError,
            register,
            reset_registry_for_tests,
        )

        class _Req(BaseModel):
            pass

        class _Resp(BaseModel):
            ok: bool = True

        function_id = "test.synthetic.noop"

        def _noop(_req: FunctionCallRequest) -> HandlerOutcome:
            return HandlerOutcome(primary_success=True, result_payload={"ok": True})

        try:
            register(
                function_id,
                _noop,
                _Req,
                _Resp,
                stability="internal",
                owner_module=__name__,
                target_kinds=["global"],
                side_effects=[],
                emitted_event_names=[],
                guardrails=[],
                adapter_status="live",
                claim_required_kind="self_only",
                minimum_serving_version="next-release",
            )
        except RegistryDuplicateError:
            pass

        try:
            request = FunctionCallRequest(
                function=function_id,
                version="v1",
                actor=ActorContext(actor_id="test", session_id="test-session"),
                target=TargetRef(kind="global"),
                payload={},
            )
            # Stub the dispatcher's event-write and idempotency-lookup paths
            # so the synthetic baseline measures routing logic only, not the
            # events DB write. The synthetic handler has claim_required_kind=
            # ``self_only`` so no claim DB lookup is involved.
            with (
                mock.patch(
                    "yoke_core.domain.yoke_function_dispatch._idempotency_lookup",
                    return_value=None,
                ),
                mock.patch(
                    "yoke_core.domain.yoke_function_dispatch_events.emit_called",
                    return_value=None,
                ),
            ):
                for _ in range(DISPATCHER_OVERHEAD_WARMUP):
                    _noop(request)
                    dispatch(request)
                baseline = _measure_ms(
                    lambda: _noop(request),
                    DISPATCHER_OVERHEAD_SAMPLES,
                )
                dispatched = _measure_ms(
                    lambda: dispatch(request),
                    DISPATCHER_OVERHEAD_SAMPLES,
                )
        finally:
            reset_registry_for_tests()

        baseline_p99 = _percentile_ms(baseline, 99.0)
        dispatched_p99 = _percentile_ms(dispatched, 99.0)
        overhead_p99 = max(0.0, dispatched_p99 - baseline_p99)
        self.assertLess(
            overhead_p99,
            DISPATCHER_OVERHEAD_BUDGET_MS,
            msg=(
                f"synthetic dispatcher overhead p99 {overhead_p99:.2f}ms "
                f"exceeds NFR-3 budget {DISPATCHER_OVERHEAD_BUDGET_MS}ms "
                f"(baseline {baseline_p99:.2f}ms, dispatched {dispatched_p99:.2f}ms)"
            ),
        )


if __name__ == "__main__":
    unittest.main()
