# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from types import SimpleNamespace

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    NOW,
    PROJECT_ID,
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)

from yoke_contracts.session_control.native_models import models_reading, native_model

from yoke_contracts.session_control.extra_usage import EXTRA_DISABLED, extra_usage

from yoke_contracts.session_control.plan_limits import (
    CURSOR_MODELS_SCOPE,
    CURSOR_OTHER_MODELS_SCOPE,
    plan_limit_window,
)

from yoke_core.domain.sessions_lifecycle_claim import claim_work

from yoke_core.domain.session_wake_meter import RECOVERY

from yoke_core.domain.steering_fleet_report_projection import report_dict

from yoke_core.domain.steering_fleet_report_render import report_body

from yoke_core.domain.steering_fleet_report_stranded import (
    KIND_METER_EXHAUSTED,
    KIND_MODEL_REMOVED,
    StrandedSession,
    stranded_section,
)

from yoke_core.domain.work_claim_targets import make_item_target

RESET = "2026-10-07T00:00:00.000000Z"

OTHER_METER = "planUsage.apiPercentUsed"

OPUS = "claude-opus-4-6"


def _pin_worker(conn, *, windows=None, native=None, model=OPUS):
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=%s, model=%s WHERE session_id=%s",
        ("cursor-cli", model, WORKER_SESSION),
    )
    payload = {}
    if windows is not None:
        payload["surface_plan_limits"] = json.dumps(
            {
                "cursor-cli": {
                    "surface": "cursor-cli",
                    "plan_tier": "Ultra",
                    "observed_at": NOW,
                    "windows": windows,
                    # Usage-based pricing off: an empty pool really stops work.
                    "extra_usage": extra_usage(
                        EXTRA_DISABLED,
                        meter="GetHardLimit.noUsageBasedAllowed",
                        reason="usage_based_pricing_off",
                    ),
                }
            }
        )
    if native is not None:
        payload["surface_native_models"] = json.dumps(native)
    if payload:
        assignments = ", ".join(f"{column} = %s" for column in payload)
        conn.execute(
            f"UPDATE session_relays SET {assignments} WHERE relay_id = 'relay-1'",
            tuple(payload.values()),
        )
    conn.commit()


def _exhausted_other_models():
    return [
        plan_limit_window(
            window_kind="monthly",
            scope=CURSOR_MODELS_SCOPE,
            meter="planUsage.autoPercentUsed",
            remaining_percent=50.0,
            resets_at=RESET,
        ),
        plan_limit_window(
            window_kind="monthly",
            scope=CURSOR_OTHER_MODELS_SCOPE,
            meter=OTHER_METER,
            remaining_percent=0.0,
            resets_at=RESET,
        ),
    ]
