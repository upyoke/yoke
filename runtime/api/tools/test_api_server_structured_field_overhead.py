"""api server structured field overhead regression coverage."""

# ruff: noqa: F401
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
import pytest

from runtime.api.tools.test_api_server import (
    DISPATCHER_OVERHEAD_BUDGET_MS,
    DISPATCHER_OVERHEAD_SAMPLES,
    DISPATCHER_OVERHEAD_WARMUP,
    _FakeProc,
    _dispatcher_available,
    _measure_ms,
    _percentile_ms,
    _structured_field_handler_registered,
    pytestmark,
)


@unittest.skipUnless(
    _structured_field_handler_registered(),
    "items.structured_field.replace not registered.",
)
class DispatcherOverheadStructuredFieldReplaceTests(unittest.TestCase):
    """Dispatcher p99 overhead for ``items.structured_field.replace``.

    Underlying ``execute_structured_write`` is mocked at the boundary so the
    measurement is pure dispatcher overhead and no live DB state is touched.
    """

    def test_dispatcher_overhead_items_structured_field_replace(self) -> None:
        from yoke_core.domain.yoke_function_dispatch import dispatch
        from yoke_contracts.api.function_call import (
            ActorContext,
            FunctionCallRequest,
            TargetRef,
        )
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        assert lookup("items.structured_field.replace") is not None

        request = FunctionCallRequest(
            function="items.structured_field.replace",
            version="v1",
            actor=ActorContext(actor_id="test", session_id="test-session"),
            target=TargetRef(kind="item", item_id=1),
            payload={"field": "spec", "content": "# microbench spec"},
            preconditions={"allow_empty": False, "allow_shrinkage": True},
            options={"sync_github_body": False, "dry_run": True},
        )
        fake_result = {
            "success": True,
            "item_id": 1,
            "field": "spec",
            "old_line_count": 0,
            "new_line_count": 1,
            "old_hash": "",
            "new_hash": "deadbeef",
            "byte_count": 17,
            "verification_status": "ok",
            "sync_status": "skipped",
            "event_ids": [],
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
        with (
            mock.patch(
                "yoke_core.domain.handlers.items_structured_field.execute_structured_write",
                return_value=fake_result,
            ) as patched_exec,
            mock.patch(
                "yoke_core.domain.handlers.items_structured_field._read_field",
                return_value="",
            ),
            mock.patch(
                "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
                return_value=fake_claim,
            ),
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
                patched_exec(item_id=1, field="spec", content="# x")
                dispatch(request)
            baseline = _measure_ms(
                lambda: patched_exec(item_id=1, field="spec", content="# x"),
                DISPATCHER_OVERHEAD_SAMPLES,
            )
            dispatched = _measure_ms(
                lambda: dispatch(request),
                DISPATCHER_OVERHEAD_SAMPLES,
            )

        baseline_p99 = _percentile_ms(baseline, 99.0)
        dispatched_p99 = _percentile_ms(dispatched, 99.0)
        overhead_p99 = max(0.0, dispatched_p99 - baseline_p99)
        self.assertLess(
            overhead_p99,
            DISPATCHER_OVERHEAD_BUDGET_MS,
            msg=(
                f"items.structured_field.replace dispatcher overhead p99 "
                f"{overhead_p99:.2f}ms exceeds NFR-3 budget "
                f"{DISPATCHER_OVERHEAD_BUDGET_MS}ms "
                f"(baseline {baseline_p99:.2f}ms, dispatched {dispatched_p99:.2f}ms)"
            ),
        )
