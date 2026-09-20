"""Sessions pinned to a model they cannot usefully resume on."""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)
from yoke_contracts.session_control.native_models import models_reading, native_model
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
    KIND_MODEL_DESELECTED,
    KIND_MODEL_REMOVED,
    StrandedSession,
    stranded_section,
)
from yoke_core.domain.work_claim_targets import make_item_target


RESET = "2026-10-07T00:00:00Z"
OTHER_METER = "planUsage.apiPercentUsed"
OPUS = "claude-opus-4-6"


def _entry(**overrides) -> StrandedSession:
    fields = dict(
        session_id=WORKER_SESSION,
        item_id=1,
        public_ref="YOK-1",
        surface="cursor-cli",
        model=OPUS,
        kind=KIND_METER_EXHAUSTED,
        preferred_model="",
        meter=OTHER_METER,
        remaining_percent=0.0,
        resets_at=RESET,
        reason=f"meter {OTHER_METER} (monthly · Other Models) 0% remaining, resets {RESET}",
        recovery=RECOVERY,
    )
    fields.update(overrides)
    return StrandedSession(**fields)


def _pin_worker(conn, *, windows=None, preferred=None, native=None, model=OPUS):
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
                }
            }
        )
    if preferred is not None:
        payload["preferred_session_models"] = json.dumps(preferred)
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


def test_stranded_section_names_count_items_and_recovery() -> None:
    lines = stranded_section(SimpleNamespace(stranded=(_entry(),)))
    assert lines[0].startswith("stranded sessions")
    assert "1 session on cursor-cli · " + OPUS in lines[1]
    assert WORKER_SESSION in lines[1]
    assert "YOK-1" in lines[1]
    assert "0%" in lines[1]
    assert RESET in lines[1]
    assert RECOVERY in lines[1]
    assert stranded_section(SimpleNamespace(stranded=())) == []


def test_an_exhausted_pool_is_named_instead_of_idle(test_db) -> None:
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    _pin_worker(conn, windows=_exhausted_other_models())

    report = compose(conn)
    body = report_body(report)

    assert report.actionable is True
    assert len(report.stranded) == 1
    assert report.stranded[0].kind == KIND_METER_EXHAUSTED
    assert report.stranded[0].meter == OTHER_METER
    assert report.stranded[0].public_ref == "YOK-1"
    assert all(holder.session_id != WORKER_SESSION for holder in report.idle)
    assert "stranded sessions" in body
    assert WORKER_SESSION in body
    assert "do not wake them" in body
    assert "idle holders" not in body
    assert report_dict(report)["stranded"][0]["kind"] == KIND_METER_EXHAUSTED


def test_the_wrong_cursor_pool_at_zero_does_not_strand_opus(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _pin_worker(
        conn,
        windows=[
            plan_limit_window(
                window_kind="monthly",
                scope=CURSOR_MODELS_SCOPE,
                meter="planUsage.autoPercentUsed",
                remaining_percent=0.0,
                resets_at=RESET,
            ),
            plan_limit_window(
                window_kind="monthly",
                scope=CURSOR_OTHER_MODELS_SCOPE,
                meter=OTHER_METER,
                remaining_percent=50.0,
                resets_at=RESET,
            ),
        ],
    )
    assert compose(conn).stranded == ()


def test_a_deselected_model_is_stranded(test_db) -> None:
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    _pin_worker(conn, preferred={"cursor-cli": "composer-1"})

    report = compose(conn)
    assert report.stranded[0].kind == KIND_MODEL_DESELECTED
    assert "composer-1" in report.stranded[0].reason
    assert report.actionable is True


def test_a_removed_model_is_stranded(test_db) -> None:
    conn = seed_steering_scope(test_db)
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=%s, model=%s WHERE session_id=%s",
        ("cursor-cli", OPUS, WORKER_SESSION),
    )
    conn.execute(
        "UPDATE session_relays SET surface_native_models=%s WHERE relay_id='relay-1'",
        (
            json.dumps(
                {
                    "cursor-cli": models_reading(
                        "cursor-cli",
                        [native_model("composer-1")],
                        source="cursor",
                        observed_at=NOW,
                    )
                }
            ),
        ),
    )
    conn.commit()
    report = compose(conn)
    cursor = [row for row in report.native_models if row.surface == "cursor-cli"]
    assert cursor and cursor[0].sample_models == ("composer-1",)
    assert report.stranded[0].kind == KIND_MODEL_REMOVED
    assert OPUS in report.stranded[0].reason


def test_stranded_identity_moves_the_fingerprint(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _pin_worker(conn, windows=_exhausted_other_models())
    before = compose(conn).fingerprint()
    _pin_worker(
        conn,
        windows=[
            plan_limit_window(
                window_kind="monthly",
                scope=CURSOR_OTHER_MODELS_SCOPE,
                meter=OTHER_METER,
                remaining_percent=50.0,
                resets_at=RESET,
            )
        ],
    )
    after = compose(conn)
    assert after.stranded == ()
    assert after.fingerprint() != before
