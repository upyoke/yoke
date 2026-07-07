"""Tests for :mod:`yoke_core.tools.api_server` and microbenches."""

from __future__ import annotations

import importlib
import io
import signal
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Callable, List
from unittest import mock

from yoke_core.tools import api_server


# NFR-3: dispatcher p99 overhead < 50ms over the underlying callable.
DISPATCHER_OVERHEAD_BUDGET_MS = 50.0
DISPATCHER_OVERHEAD_SAMPLES = 100
DISPATCHER_OVERHEAD_WARMUP = 10


def _dispatcher_available() -> bool:
    try:
        importlib.import_module("yoke_core.domain.yoke_function_dispatch")
        importlib.import_module("yoke_core.domain.yoke_function_registry")
        importlib.import_module("yoke_contracts.api.function_call")
    except Exception:
        return False
    return True


def _structured_field_handler_registered() -> bool:
    if not _dispatcher_available():
        return False
    try:
        from yoke_core.domain.handlers import (
            __init_register__ as _init_register,
        )
        from yoke_core.domain.yoke_function_registry import lookup
    except Exception:
        return False
    try:
        _init_register.register_all_handlers()
    except Exception:
        pass  # Already registered — lookup tells us either way.
    return lookup("items.structured_field.replace") is not None


def _percentile_ms(samples: List[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * len(ordered) - 1))))
    return ordered[idx]


def _measure_ms(call: Callable[[], object], iterations: int) -> List[float]:
    samples: List[float] = []
    for _ in range(iterations):
        t0 = time.process_time()
        call()
        samples.append((time.process_time() - t0) * 1000.0)
    return samples


class _FakeProc:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid


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
        with self._patch_root(), mock.patch.object(
            api_server, "_is_alive", return_value=True
        ), redirect_stdout(buf):
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
        with self._patch_root(), mock.patch.object(
            api_server, "_is_alive", return_value=False
        ), mock.patch("yoke_core.tools.api_server.subprocess.Popen", side_effect=fake_popen), redirect_stdout(buf):
            rc = api_server.cmd_start()
        self.assertEqual(rc, 0)
        self.assertIn("uvicorn", " ".join(launched["args"]))
        self.assertEqual(pid_file.read_text(encoding="utf-8").strip(), "1234")
        popen_kwargs = launched["kwargs"]
        actual = (popen_kwargs["stdin"], popen_kwargs["stderr"], popen_kwargs["start_new_session"])
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
        with self._patch_root(), mock.patch.object(
            api_server, "_is_alive", side_effect=fake_is_alive
        ), mock.patch("yoke_core.tools.api_server.os.kill", side_effect=fake_kill), redirect_stdout(buf):
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
    "Yoke function dispatcher not present on this branch (AC-17.6(a)).",
)
class DispatcherOverheadSyntheticTests(unittest.TestCase):
    """AC-17.6(a): dispatcher p99 overhead over a synthetic no-op handler.

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
                function_id, _noop, _Req, _Resp,
                stability="internal", owner_module=__name__,
                target_kinds=["global"], side_effects=[], emitted_event_names=[],
                guardrails=[], adapter_status="live",
                claim_required_kind="self_only",
            )
        except RegistryDuplicateError:
            pass

        try:
            request = FunctionCallRequest(
                function=function_id, version="v1",
                actor=ActorContext(actor_id="test", session_id="test-session"),
                target=TargetRef(kind="global"), payload={},
            )
            # Stub the dispatcher's event-write and idempotency-lookup paths
            # so the synthetic baseline measures routing logic only, not the
            # events DB write. The synthetic handler has claim_required_kind=
            # ``self_only`` so no claim DB lookup is involved.
            with mock.patch(
                "yoke_core.domain.yoke_function_dispatch._idempotency_lookup",
                return_value=None,
            ), mock.patch(
                "yoke_core.domain.yoke_function_dispatch_events.emit_called",
                return_value=None,
            ):
                for _ in range(DISPATCHER_OVERHEAD_WARMUP):
                    _noop(request)
                    dispatch(request)
                baseline = _measure_ms(
                    lambda: _noop(request), DISPATCHER_OVERHEAD_SAMPLES,
                )
                dispatched = _measure_ms(
                    lambda: dispatch(request), DISPATCHER_OVERHEAD_SAMPLES,
                )
        finally:
            reset_registry_for_tests()

        baseline_p99 = _percentile_ms(baseline, 99.0)
        dispatched_p99 = _percentile_ms(dispatched, 99.0)
        overhead_p99 = max(0.0, dispatched_p99 - baseline_p99)
        self.assertLess(
            overhead_p99, DISPATCHER_OVERHEAD_BUDGET_MS,
            msg=(
                f"synthetic dispatcher overhead p99 {overhead_p99:.2f}ms "
                f"exceeds NFR-3 budget {DISPATCHER_OVERHEAD_BUDGET_MS}ms "
                f"(baseline {baseline_p99:.2f}ms, dispatched {dispatched_p99:.2f}ms)"
            ),
        )


@unittest.skipUnless(
    _structured_field_handler_registered(),
    "items.structured_field.replace not registered (AC-17.6(b)).",
)
class DispatcherOverheadStructuredFieldReplaceTests(unittest.TestCase):
    """AC-17.6(b): dispatcher p99 overhead for ``items.structured_field.replace``.

    Underlying ``execute_structured_write`` is mocked at the boundary so the
    measurement is pure dispatcher overhead and no live DB state is touched.
    """

    def test_dispatcher_overhead_items_structured_field_replace(self) -> None:
        from yoke_core.domain.yoke_function_dispatch import dispatch
        from yoke_contracts.api.function_call import (
            ActorContext, FunctionCallRequest, TargetRef,
        )
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        assert lookup("items.structured_field.replace") is not None

        request = FunctionCallRequest(
            function="items.structured_field.replace", version="v1",
            actor=ActorContext(actor_id="test", session_id="test-session"),
            target=TargetRef(kind="item", item_id=1),
            payload={"field": "spec", "content": "# microbench spec"},
            preconditions={"allow_empty": False, "allow_shrinkage": True},
            options={"sync_github_body": False, "rebuild_board": False, "dry_run": True},
        )
        fake_result = {
            "success": True, "item_id": 1, "field": "spec",
            "old_line_count": 0, "new_line_count": 1,
            "old_hash": "", "new_hash": "deadbeef",
            "byte_count": 17, "verification_status": "ok",
            "sync_status": "skipped", "event_ids": [],
        }
        # Patch the handler's import binding (the symbol the handler actually
        # calls), not the source module — ``from X import Y`` copies the name
        # into the handler module's namespace at import time. Also stub
        # ``_read_field`` and the dispatcher claim/idempotency lookups so the
        # microbench measures only dispatcher + handler control flow, not
        # DB I/O.
        fake_claim = {
            "session_id": "test-session",
            "released_at": None,
            "claim_type": "default",
        }
        with mock.patch(
            "yoke_core.domain.handlers.items_structured_field.execute_structured_write",
            return_value=fake_result,
        ) as patched_exec, mock.patch(
            "yoke_core.domain.handlers.items_structured_field._read_field",
            return_value="",
        ), mock.patch(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            return_value=fake_claim,
        ), mock.patch(
            "yoke_core.domain.yoke_function_dispatch._idempotency_lookup",
            return_value=None,
        ), mock.patch(
            "yoke_core.domain.yoke_function_dispatch_events.emit_called",
            return_value=None,
        ):
            for _ in range(DISPATCHER_OVERHEAD_WARMUP):
                patched_exec(item_id=1, field="spec", content="# x")
                dispatch(request)
            baseline = _measure_ms(
                lambda: patched_exec(item_id=1, field="spec", content="# x"),
                DISPATCHER_OVERHEAD_SAMPLES,
            )
            dispatched = _measure_ms(
                lambda: dispatch(request), DISPATCHER_OVERHEAD_SAMPLES,
            )

        baseline_p99 = _percentile_ms(baseline, 99.0)
        dispatched_p99 = _percentile_ms(dispatched, 99.0)
        overhead_p99 = max(0.0, dispatched_p99 - baseline_p99)
        self.assertLess(
            overhead_p99, DISPATCHER_OVERHEAD_BUDGET_MS,
            msg=(
                f"items.structured_field.replace dispatcher overhead p99 "
                f"{overhead_p99:.2f}ms exceeds NFR-3 budget "
                f"{DISPATCHER_OVERHEAD_BUDGET_MS}ms "
                f"(baseline {baseline_p99:.2f}ms, dispatched {dispatched_p99:.2f}ms)"
            ),
        )


if __name__ == "__main__":
    unittest.main()
