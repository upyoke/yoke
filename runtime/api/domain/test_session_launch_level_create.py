"""A level launch is created, replayed, and retried through the ordinary path."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.session_control.models import (
    LaunchCreateRequest,
    LaunchPreviewRequest,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import LEVEL_NO_CAPACITY
from yoke_core.domain.session_launch_level_selection import preview_level_launch
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import get_launch, update_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    assigned_launch,
    authorization,
)
from runtime.api.domain.test_session_launch_handler_deadlines import (
    _request,
    _wire_handler,
)


@pytest.fixture(autouse=True)
def _no_live_workers(monkeypatch):
    pin_live_workers(monkeypatch, {})


def _meters(conn, machine_id: str, surface: str, remaining: float) -> None:
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE relay_id = ?",
        (
            json.dumps({surface: {"plan_tier": "max", "windows": [weekly(remaining)]}}),
            f"relay-{machine_id}-{surface}",
        ),
    )
    conn.commit()


def _two_options(*, claude: float, codex: float):
    conn = level_connection(CODEX_SOL, CLAUDE_OPUS)
    add_surface(conn, "m-codex", "codex-cli", [weekly(codex)])
    add_surface(conn, "m-claude", "claude-cli", [weekly(claude)])
    return conn


def _level_request(key: str = "level-key", level: str = LEVEL) -> LaunchRequest:
    return LaunchRequest(
        project_id=10,
        executor_surface="",
        instructions="Report the current evidence.",
        idempotency_key=key,
        level=level,
    )


def _create(conn, request: LaunchRequest | None = None):
    return create_launch(
        conn, auth=authorization(), request=request or _level_request(), now=NOW
    )


def test_a_level_launch_stores_the_level_and_resolves_the_chosen_option() -> None:
    conn = _two_options(claude=20.0, codex=40.0)

    launch = _create(conn).launch

    assert launch.requested_level == LEVEL
    assert launch.requested_model is None
    assert launch.requested_reasoning_effort is None
    assert launch.requested_context_window_tokens is None
    assert launch.selected_surface == "codex-cli"
    assert launch.assigned_machine_id == "m-codex"
    assert launch.resolved_model == CODEX_SOL["model"]
    assert launch.resolved_reasoning_effort == CODEX_SOL["reasoning_effort"]
    assert str(launch.placement_reason).startswith(f"level {LEVEL}: most headroom")
    evidence = json.loads(str(launch.level_placement))
    assert evidence["level"] == LEVEL
    assert evidence["chosen"]["surface"] == "codex-cli"
    assert len(evidence["candidates"]) == 2


def test_the_public_record_names_a_level_selection_and_its_evidence() -> None:
    conn = _two_options(claude=20.0, codex=40.0)

    record = public_launch_record(_create(conn).launch)

    assert record["selection"] == "level"
    assert record["requested_level"] == LEVEL
    assert record["level_placement"]["chosen"]["model"] == CODEX_SOL["model"]


def test_an_exact_surface_launch_is_recorded_as_an_override() -> None:
    conn = _two_options(claude=20.0, codex=40.0)

    launch = assigned_launch(conn, surface="codex-cli", machine_id="m-codex")
    record = public_launch_record(launch)

    assert launch.requested_level is None
    assert launch.level_placement is None
    assert record["selection"] == "override"
    assert record["level_placement"] is None


def test_a_level_with_no_capacity_is_refused_and_stores_nothing() -> None:
    conn = _two_options(claude=0.0, codex=0.0)

    with pytest.raises(SessionLaunchError) as raised:
        _create(conn)

    assert raised.value.code == LEVEL_NO_CAPACITY
    assert f"No {LEVEL} option has capacity" in str(raised.value)
    assert conn.execute("SELECT count(*) FROM session_launches").fetchone()[0] == 0


def test_a_level_preview_with_no_capacity_is_not_launchable() -> None:
    conn = _two_options(claude=0.0, codex=0.0)

    request, preview = preview_level_launch(
        conn,
        auth=authorization(),
        request=_level_request(),
        now=NOW,
        eligibility=derive_launch_eligibility,
    )

    assert preview.outcome == LEVEL_NO_CAPACITY
    assert preview.launchable is False
    assert request.executor_surface == ""
    assert preview.to_dict()["level_placement"]["chosen"] is None


def test_a_replay_names_the_same_level_even_when_placement_would_differ() -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    first = _create(conn)
    _meters(conn, "m-codex", "codex-cli", 1.0)

    replay = _create(conn)

    assert replay.deduplicated is True
    assert replay.launch.launch_id == first.launch.launch_id
    assert replay.launch.selected_surface == "codex-cli"


def test_a_retry_places_the_level_again() -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    launch = _create(conn).launch
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    _meters(conn, "m-codex", "codex-cli", 0.0)

    retried = retry_launch(
        conn, launch_id=launch.launch_id, auth=authorization(), now=NOW
    )

    assert retried.state == "assigned"
    assert retried.requested_level == LEVEL
    assert retried.requested_model is None
    assert retried.selected_surface == "claude-cli"
    assert retried.assigned_machine_id == "m-claude"
    assert retried.resolved_model == CLAUDE_OPUS["model"]
    evidence = json.loads(str(get_launch(conn, launch.launch_id).level_placement))
    assert evidence["chosen"]["surface"] == "claude-cli"


def test_a_retry_with_no_capacity_left_is_refused_naming_the_pools() -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    launch = _create(conn).launch
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    _meters(conn, "m-codex", "codex-cli", 0.0)
    _meters(conn, "m-claude", "claude-cli", 0.0)

    with pytest.raises(SessionLaunchError) as raised:
        retry_launch(conn, launch_id=launch.launch_id, auth=authorization(), now=NOW)

    assert raised.value.code == LEVEL_NO_CAPACITY
    assert "pool exhausted" in str(raised.value)


def test_the_preview_handler_reports_the_level_option_as_the_knob_source(
    monkeypatch,
) -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_preview_payload.utc_now", lambda: NOW
    )

    outcome = handlers.handle_launch_preview(
        _request(
            "session_control.launch.preview",
            {"project": "launch-project", "level": "senior"},
        )
    )

    assert outcome.primary_success, outcome.error
    payload = outcome.result_payload
    assert payload["requested_level"] == LEVEL
    assert payload["model"] == CODEX_SOL["model"]
    assert payload["model_source"] == f"level {LEVEL} option"
    assert payload["level_placement"]["chosen"]["machine_id"] == "m-codex"


@pytest.mark.parametrize(
    "knob",
    [
        {"executor_surface": "claude-cli"},
        {"model": "claude-opus-5-5"},
        {"reasoning_effort": "high"},
        {"context_window_tokens": 1_000_000},
        {"allow_surface_fallback": True},
    ],
)
def test_a_level_beside_any_exact_knob_is_a_request_conflict(knob) -> None:
    with pytest.raises(ValueError, match="level_selection_conflict"):
        LaunchPreviewRequest(project="yoke", level="SENIOR", **knob)


def test_a_preview_naming_neither_level_nor_surface_is_refused() -> None:
    with pytest.raises(ValueError, match="launch_selection_missing"):
        LaunchPreviewRequest(project="yoke")


def test_a_requested_level_is_normalized_to_upper_case() -> None:
    request = LaunchCreateRequest(
        project="yoke", level=" senior ", item="YOK-1", idempotency_key="k"
    )

    assert request.level == "SENIOR"
    assert request.executor_surface is None
