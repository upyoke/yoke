"""Surface-only staffing selects its item level without crossing surfaces."""

from dataclasses import replace
import json

import pytest

from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    LEVEL,
    pin_live_workers,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_level_create import (
    _level_request,
    _meters,
    _two_options,
)
from yoke_core.domain import item_ref_resolution, workflow_stage_levels
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import SessionLaunchError


@pytest.fixture(autouse=True)
def item_level(monkeypatch):
    pin_live_workers(monkeypatch, {})
    monkeypatch.setattr(item_ref_resolution, "resolve_item_ref_or_none", lambda *a, **k: 41)
    monkeypatch.setattr(
        workflow_stage_levels, "item_stage_level", lambda *a, **k: {"level": LEVEL}
    )


def _surface_request(surface="codex-cli", **fields):
    return replace(
        _level_request(), level=None, item="LP-41", executor_surface=surface, **fields
    )


def _create(conn, request=None):
    return create_launch(
        conn, auth=authorization(), request=request or _surface_request(), now=NOW
    )


@pytest.mark.parametrize(
    "surface,option", [("codex-cli", CODEX_SOL), ("claude-cli", CLAUDE_OPUS)]
)
def test_surface_only_staffing_selects_a_qualifying_option(surface, option):
    conn = _two_options(claude=80.0, codex=10.0)

    launch = _create(conn, _surface_request(surface)).launch

    assert launch.requested_level is None
    assert launch.requested_surface == surface
    assert launch.selected_surface == surface
    assert launch.requested_model is None
    assert launch.resolved_model == option["model"]
    assert launch.resolved_reasoning_effort == option["min_effort"]
    candidates = json.loads(launch.level_placement)["candidates"]
    assert {candidate["surface"] for candidate in candidates} == {surface}


def test_no_capacity_on_the_surface_refuses_with_launch_flags_and_stores_nothing():
    conn = _two_options(claude=80.0, codex=0.0)

    with pytest.raises(SessionLaunchError) as refused:
        _create(conn)

    assert refused.value.code == "level_no_capacity"
    message = str(refused.value)
    assert "on codex-cli" in message
    assert "pool exhausted" in message
    assert "--surface codex-cli --model MODEL --reasoning-effort EFFORT" in message
    assert "/model" not in message
    assert conn.execute("SELECT count(*) FROM session_launches").fetchone()[0] == 0


def test_no_model_option_for_the_surface_names_the_launch_recovery():
    from runtime.api.domain.session_launch_level_test_support import (
        add_surface,
        level_connection,
        weekly,
    )

    conn = level_connection(CLAUDE_OPUS)
    add_surface(conn, "m-codex", "codex-cli", [weekly(80.0)])

    with pytest.raises(SessionLaunchError) as refused:
        _create(conn)

    assert "No SENIOR option has capacity on codex-cli" in str(refused.value)
    assert "--model MODEL --reasoning-effort EFFORT" in str(refused.value)


def test_replay_keeps_the_surface_while_capacity_changes():
    conn = _two_options(claude=10.0, codex=80.0)
    first = _create(conn).launch
    _meters(conn, "m-codex", "codex-cli", 0.0)

    replay = _create(conn)

    assert replay.deduplicated
    assert replay.launch.launch_id == first.launch_id
    with pytest.raises(SessionLaunchError, match="different launch request"):
        _create(conn, _surface_request("claude-cli"))


def test_retry_refuses_when_only_another_surface_has_capacity():
    conn = _two_options(claude=10.0, codex=80.0)
    first = _create(conn).launch
    update_launch(conn, first.launch_id, state="failed", result_code="native_failed")
    _meters(conn, "m-codex", "codex-cli", 0.0)

    with pytest.raises(SessionLaunchError) as refused:
        retry_launch(conn, launch_id=first.launch_id, auth=authorization(), now=NOW)

    assert refused.value.code == "level_no_capacity"
    assert "--surface codex-cli --model MODEL --reasoning-effort EFFORT" in str(refused.value)


def test_unrestricted_level_retry_can_still_change_surfaces():
    conn = _two_options(claude=10.0, codex=80.0)
    first = _create(conn, _level_request()).launch
    assert first.requested_level == LEVEL
    update_launch(conn, first.launch_id, state="failed", result_code="native_failed")
    _meters(conn, "m-codex", "codex-cli", 0.0)

    retried = retry_launch(conn, launch_id=first.launch_id, auth=authorization(), now=NOW)

    assert retried.selected_surface == "claude-cli"


def test_explicit_model_keeps_the_exact_selection_path():
    request = _surface_request(model="gpt-6.1-sol", reasoning_effort="high")
    resolved = workflow_stage_levels.default_launch_level(None, request)
    assert resolved is request


def test_missing_stage_level_explains_launch_flags(monkeypatch):
    monkeypatch.setattr(workflow_stage_levels, "item_stage_level", lambda *a, **k: None)

    with pytest.raises(SessionLaunchError) as refused:
        workflow_stage_levels.default_launch_level(None, _surface_request())

    assert refused.value.code == "launch_model_required"
    assert "--surface codex-cli --model MODEL --reasoning-effort EFFORT" in str(refused.value)


def test_surface_selection_uses_the_best_machine_capacity():
    from runtime.api.domain.session_launch_level_test_support import add_surface, weekly

    conn = _two_options(claude=90.0, codex=10.0)
    add_surface(conn, "m-more-codex", "codex-cli", [weekly(80.0)])

    launch = _create(conn).launch

    assert launch.selected_surface == "codex-cli"
    assert launch.assigned_machine_id == "m-more-codex"


def test_a_surface_request_cannot_replay_an_unrestricted_level_launch():
    conn = _two_options(claude=10.0, codex=80.0)
    _create(conn, _level_request())

    with pytest.raises(SessionLaunchError, match="different launch request"):
        _create(conn)
