"""Stage defaults and item overrides choose the effective launch level."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_core.domain import item_level_override, workflow_stage_levels as levels
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definitions
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.workflow_definition_validation import validate_workflow_definition
from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_terminal_admission import _seed_pinned_item


@pytest.fixture
def ordered_levels(monkeypatch):
    ordered = tuple(
        SimpleNamespace(name=name, glyph="🦉")
        for name in ("INTERN", "JUNIOR", "SENIOR", "PRINCIPAL")
    )
    monkeypatch.setattr(
        item_level_override, "effective_levels", lambda *_a: (ordered, "universe")
    )
    return ordered


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"shift": -1}, "JUNIOR"),
        ({"shift": 1}, "PRINCIPAL"),
        ({"shift": -99}, "INTERN"),
        ({"shift": 99}, "PRINCIPAL"),
        ({"shift": -2, "min": "JUNIOR"}, "JUNIOR"),
        ({"shift": 2, "max": "SENIOR"}, "SENIOR"),
        ({"min": "JUNIOR", "max": "JUNIOR"}, "JUNIOR"),
    ],
)
def test_shift_and_bounds_use_the_same_ordered_levels(
    ordered_levels, override, expected
):
    resolved = levels.resolve_stage_level(
        None,
        project_id=10,
        stage={"id": "work", "level": "SENIOR"},
        posture={"level": {**override, "reason": "Staffing decision"}},
    )
    assert resolved["level"] == expected
    assert resolved["stage_level"] == "SENIOR"


def test_clear_override_returns_to_stage_default(ordered_levels):
    assert (
        levels.resolve_stage_level(
            None, project_id=10, stage={"id": "work", "level": "SENIOR"}, posture={}
        )["level"]
        == "SENIOR"
    )


def test_every_shipped_nonterminal_stage_defaults_to_senior():
    for fixture in builtin_workflow_definitions():
        definition = fixture["definition"]
        validate_workflow_definition(definition)
        assert "level" in definition["policies"]["item_posture_allowlist"]
        for stage in definition["stages"]:
            if stage["id"] in definition["terminal_stage_ids"]:
                assert "level" not in stage
            else:
                assert stage["level"] == "SENIOR"


def test_create_uses_live_stage_level_and_explicit_level_wins(monkeypatch):
    pin_live_workers(monkeypatch, {})
    conn = level_connection(CODEX_SOL)
    add_surface(conn, "worker-machine", "codex-cli", [weekly(50)])
    ref = _seed_pinned_item(conn, status="implementing")
    conn.execute("ALTER TABLE items ADD COLUMN workflow_posture TEXT DEFAULT '{}'")
    conn.commit()
    ask = LaunchRequest(
        project_id=10,
        executor_surface="",
        item=ref,
        instructions="Resume the item",
        idempotency_key="stage-default",
    )
    launch = create_launch(conn, auth=authorization(), request=ask, now=NOW).launch
    assert launch.requested_level == "SENIOR"
    conn.execute(
        "UPDATE items SET workflow_posture=?",
        (json.dumps({"level": {"max": "SENIOR", "reason": "Keep the ceiling"}}),),
    )
    conn.commit()
    from dataclasses import replace

    explicit = levels.default_launch_level(conn, replace(ask, level="JUNIOR"))
    assert explicit.level == "JUNIOR"


def test_no_stage_level_and_no_explicit_level_refuses_before_writes():
    conn = level_connection(CODEX_SOL)
    ask = LaunchRequest(
        project_id=10,
        executor_surface="",
        instructions="Unassigned",
        idempotency_key="missing-level",
    )
    with pytest.raises(SessionLaunchError) as failure:
        create_launch(conn, auth=authorization(), request=ask, now=NOW)
    assert failure.value.code == "stage_level_missing"
    assert "--level LEVEL" in str(failure.value)
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0


@pytest.mark.parametrize(
    "stage_level,override",
    [
        ("MISSING", None),
        ("SENIOR", {"shift": 1}),
        ("SENIOR", {}),
    ],
)
def test_invalid_stage_or_override_returns_named_recovery(
    ordered_levels, stage_level, override
):
    with pytest.raises(levels.StageLevelError) as failure:
        levels.resolve_stage_level(
            None,
            project_id=10,
            stage={"id": "work", "level": stage_level},
            posture={} if override is None else {"level": override},
        )
    assert failure.value.code == "stage_level_invalid"
    assert "Recovery:" in str(failure.value)
