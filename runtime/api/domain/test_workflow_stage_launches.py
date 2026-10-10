"""Real launch placement consumes the effective stage default exactly once."""

from dataclasses import replace
import json

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_selection import preview_level_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.universe_levels import write_universe_levels
from yoke_core.domain.workflow_stage_levels import default_launch_level
from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_terminal_admission import (
    _pin_definition,
    _seed_pinned_item,
)


def staged_launch(monkeypatch, *, capacity=50):
    pin_live_workers(monkeypatch, {})
    conn = level_connection(CODEX_SOL)
    write_universe_levels(conn, list(DEFAULT_LEVELS), actor_id=1)
    add_surface(conn, "worker-machine", "codex-cli", [weekly(capacity)])
    definition = _pin_definition()
    for stage in definition["stages"]:
        if stage["id"] == "implementing":
            stage["level"] = "INTERN"
    ref = _seed_pinned_item(conn, status="implementing", definition=definition)
    conn.execute("ALTER TABLE items ADD COLUMN workflow_posture TEXT DEFAULT '{}'")
    conn.execute(
        "UPDATE items SET workflow_posture=?",
        (
            json.dumps(
                {"level": {"shift": 1, "max": "SENIOR", "reason": "One step up"}}
            ),
        ),
    )
    conn.commit()
    return conn, LaunchRequest(
        project_id=10,
        executor_surface="",
        item=ref,
        instructions="Resume the same item",
        idempotency_key="effective-stage",
    )


def test_default_create_applies_one_shift_and_places_the_effective_level(monkeypatch):
    conn, request = staged_launch(monkeypatch)
    resolved = default_launch_level(conn, request)
    assert request.level is None
    assert default_launch_level(conn, resolved) == resolved
    launch = create_launch(conn, auth=authorization(), request=request, now=NOW).launch
    assert launch.requested_level == "JUNIOR"
    assert launch.resolved_model == "gpt-5.6-terra"
    assert json.loads(launch.level_placement)["level"] == "JUNIOR"


def test_effective_default_preview_matches_create_without_double_shift(monkeypatch):
    conn, request = staged_launch(monkeypatch)
    placed, preview = preview_level_launch(
        conn,
        auth=authorization(),
        request=default_launch_level(conn, request),
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )
    assert preview.launchable
    assert placed.level == "JUNIOR"
    assert placed.model == "gpt-5.6-terra"
    assert preview.level_placement["level"] == "JUNIOR"
    assert default_launch_level(conn, placed) == placed
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0


def test_effective_default_without_capacity_names_that_level_before_writing(
    monkeypatch,
):
    conn, request = staged_launch(monkeypatch, capacity=0)
    with pytest.raises(SessionLaunchError) as error:
        create_launch(conn, auth=authorization(), request=request, now=NOW)
    assert error.value.code == "level_no_capacity"
    assert "JUNIOR" in str(error.value)
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0


def test_explicit_level_wins_even_above_the_item_ceiling(monkeypatch):
    conn, request = staged_launch(monkeypatch)
    launch = create_launch(
        conn, auth=authorization(), request=replace(request, level="PRINCIPAL"), now=NOW
    ).launch
    assert launch.requested_level == "PRINCIPAL"
    assert launch.resolved_model == "gpt-6-astra"


def test_exact_operator_selection_bypasses_the_stage_and_item_default(monkeypatch):
    conn, request = staged_launch(monkeypatch)
    launch = create_launch(
        conn,
        auth=authorization(),
        request=replace(
            request,
            executor_surface="codex-cli",
            model=CODEX_SOL["model"],
            reasoning_effort=CODEX_SOL["reasoning_effort"],
        ),
        now=NOW,
    ).launch
    assert launch.requested_level is None
    assert launch.resolved_model == CODEX_SOL["model"]


def test_handoff_compares_effective_level_after_bounds_not_the_stage_baseline(
    monkeypatch,
):
    from yoke_core.domain.workflow_level_handoff import level_handoff

    conn, request = staged_launch(monkeypatch)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN execution_level TEXT")
    conn.execute(
        "UPDATE harness_sessions SET execution_level='SENIOR' WHERE session_id='caller'"
    )
    assert (
        level_handoff(conn, item_id=41, session_id="caller", stage_id="release") is None
    )
    conn.execute(
        "UPDATE items SET workflow_posture=?",
        (json.dumps({"level": {"shift": 1, "reason": "One step up"}}),),
    )
    result = level_handoff(conn, item_id=41, session_id="caller", stage_id="release")
    assert result["level"] == "PRINCIPAL"
    assert result["stage_id"] == "release"
    assert f"--item {request.item}" in result["next_command"]


def test_historical_pin_without_stage_levels_names_explicit_selection_recovery(
    monkeypatch,
):
    from yoke_core.domain.builtin_workflow_canon import canon_generations

    pin_live_workers(monkeypatch, {})
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "worker-machine", "codex-cli", [weekly(50)])
    historical = next(
        row.definition
        for row in canon_generations("dash")
        if row.definition["schema_version"] == 4
        and all("level" not in stage for stage in row.definition["stages"])
    )
    ref = _seed_pinned_item(conn, status="implementing", definition=historical)
    conn.execute("ALTER TABLE items ADD COLUMN workflow_posture TEXT DEFAULT '{}'")
    request = LaunchRequest(
        project_id=10,
        executor_surface="",
        item=ref,
        instructions="Resume",
        idempotency_key="historical-pin",
    )
    with pytest.raises(SessionLaunchError) as error:
        create_launch(conn, auth=authorization(), request=request, now=NOW)
    assert error.value.code == "stage_level_missing"
    assert "--level LEVEL" in str(error.value)
    launch = create_launch(
        conn, auth=authorization(), request=replace(request, level="SENIOR"), now=NOW
    ).launch
    assert launch.requested_level == "SENIOR"
