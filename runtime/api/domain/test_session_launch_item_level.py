"""An item-bound launch at a named level records that level on the item."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from runtime.api.domain.session_launch_level_test_support import LEVEL, pin_live_workers
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_level_create import (
    _level_request,
    _two_options,
)
from runtime.api.domain.test_session_launch_terminal_admission import _create_conn
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain import session_launch_requests
from yoke_core.domain.item_level_override import LEVEL_POSTURE_KEY
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.session_launch_item_level import (
    DEFAULT_LEVEL_REASON,
    pin_item_level,
)
from yoke_core.domain.session_launch_mandate import launch_request_for_create
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRequest,
    SessionLaunchError,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_core.domain.workflow_stage_levels import item_stage_level

PINNED = "JUNIOR"
SEEDED_ITEM = "LP-41"


@pytest.fixture(autouse=True)
def _no_live_workers(monkeypatch):
    pin_live_workers(monkeypatch, {})


def _seed(conn, *, item_id: int = 3101, status: str = "idea") -> int:
    return int(insert_item(conn, id=item_id, workflow_id="dash", status=status)["id"])


def _pin_request(conn, item_id: int, **fields) -> LaunchRequest:
    project_id = conn.execute(
        "SELECT project_id FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    base = {
        "project_id": int(project_id),
        "executor_surface": "",
        "instructions": "Report the current evidence.",
        "idempotency_key": "pin-key",
        "item": render_item_ref(conn, item_id, required=True),
        "level": PINNED,
        "level_reason": "well-specified change",
    }
    return LaunchRequest(**{**base, **fields})


def _stored(conn, item_id: int) -> dict:
    raw = conn.execute(
        "SELECT workflow_posture FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def _pin(conn, item_id: int, **fields):
    return pin_item_level(
        conn,
        request=_pin_request(conn, item_id, **fields),
        auth=LaunchAuthorization(
            actor_id=1, session_id="steering", can_operate_project=True
        ),
    )


def test_the_launch_level_becomes_the_item_level_for_every_stage() -> None:
    with test_database() as conn:
        item_id = _seed(conn)

        receipt = _pin(conn, item_id)

        assert receipt == {
            "level": PINNED,
            "reason": "well-specified change",
            "changed": True,
            "previous": None,
        }
        assert _stored(conn, item_id)[LEVEL_POSTURE_KEY] == {
            "min": PINNED,
            "max": PINNED,
            "reason": "well-specified change",
        }
        runtime = load_item_workflow_runtime(conn, item_id)
        live = [
            stage["id"]
            for stage in runtime.definition["stages"]
            if stage["id"] not in runtime.terminal_stage_ids
        ]
        assert len(live) > 1
        assert {
            item_stage_level(conn, item_id, stage_id=stage)["level"] for stage in live
        } == {PINNED}


def test_a_pin_replaces_an_earlier_override_and_reports_it() -> None:
    with test_database() as conn:
        item_id = _seed(conn)
        earlier = {"shift": -1, "reason": "routine"}
        amend_item_posture(
            conn, item_id=item_id, key="level", value=earlier, reason="staffing"
        )

        receipt = _pin(conn, item_id)

        assert receipt["changed"] is True
        assert receipt["previous"] == earlier
        assert _stored(conn, item_id)[LEVEL_POSTURE_KEY]["min"] == PINNED


def test_repeating_the_same_pin_reports_nothing_changed() -> None:
    with test_database() as conn:
        item_id = _seed(conn)
        _pin(conn, item_id)

        receipt = _pin(conn, item_id)

        assert receipt["changed"] is False
        assert receipt["previous"] == {
            "min": PINNED,
            "max": PINNED,
            "reason": "well-specified change",
        }


@pytest.mark.parametrize(
    "unpinned",
    [{"item": None}, {"level": None}, {"level_reason": None}],
    ids=["itemless", "stage-level default", "no recorded reason"],
)
def test_a_launch_that_asked_for_no_item_level_leaves_posture_alone(unpinned) -> None:
    with test_database() as conn:
        item_id = _seed(conn)

        assert _pin(conn, item_id, **unpinned) is None
        assert LEVEL_POSTURE_KEY not in _stored(conn, item_id)


def test_a_terminal_item_refuses_naming_the_recovery() -> None:
    with test_database() as conn:
        item_id = _seed(conn, status="done")

        with pytest.raises(SessionLaunchError) as raised:
            _pin(conn, item_id)

    assert raised.value.code == "item_level_not_recordable"
    assert "terminal stage" in str(raised.value)
    assert "launch without --level" in str(raised.value)


def test_a_level_the_project_does_not_read_refuses() -> None:
    with test_database() as conn:
        item_id = _seed(conn)

        with pytest.raises(SessionLaunchError) as raised:
            _pin(conn, item_id, level="WIZARD")

        assert LEVEL_POSTURE_KEY not in _stored(conn, item_id)

    assert raised.value.code == "item_level_not_recordable"
    assert "WIZARD" in str(raised.value)


def _item_level_request(**fields) -> LaunchRequest:
    return replace(
        _level_request(),
        item=SEEDED_ITEM,
        level_reason="well-specified change",
        **fields,
    )


@pytest.fixture
def pins(monkeypatch) -> list[LaunchRequest]:
    seen: list[LaunchRequest] = []

    def record(conn, *, request, auth):
        seen.append(request)
        return {
            "level": request.level,
            "reason": request.level_reason,
            "changed": True,
            "previous": None,
        }

    monkeypatch.setattr(session_launch_requests, "pin_item_level", record)
    return seen


def test_a_created_launch_returns_the_item_level_it_recorded(pins) -> None:
    conn = _two_options(claude=20.0, codex=40.0)

    outcome = create_launch(
        conn, auth=authorization(), request=_item_level_request(), now=NOW
    )

    assert [request.level for request in pins] == [LEVEL]
    assert outcome.item_level == {
        "level": LEVEL,
        "reason": "well-specified change",
        "changed": True,
        "previous": None,
    }


def test_a_launch_that_cannot_be_placed_pins_nothing(pins) -> None:
    conn = _two_options(claude=0.0, codex=0.0)

    with pytest.raises(SessionLaunchError):
        create_launch(
            conn, auth=authorization(), request=_item_level_request(), now=NOW
        )

    assert pins == []


def test_a_replayed_create_pins_nothing_again(pins) -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    request = _item_level_request()
    create_launch(conn, auth=authorization(), request=request, now=NOW)

    replay = create_launch(conn, auth=authorization(), request=request, now=NOW)

    assert replay.deduplicated is True
    assert replay.item_level is None
    assert len(pins) == 1


def test_a_launch_that_fails_after_the_pin_rolls_the_pin_back(
    monkeypatch,
) -> None:
    conn = _two_options(claude=20.0, codex=40.0)
    conn.execute("CREATE TABLE pinned (level TEXT)")
    conn.commit()

    def write(conn, *, request, auth):
        conn.execute("INSERT INTO pinned VALUES (?)", (request.level,))
        return {"level": request.level}

    def refuse(*_args, **_kwargs):
        raise SessionLaunchError("model_unavailable", "the model is not offered")

    monkeypatch.setattr(session_launch_requests, "pin_item_level", write)
    monkeypatch.setattr(session_launch_requests, "validate_model_selection", refuse)

    with pytest.raises(SessionLaunchError):
        create_launch(
            conn, auth=authorization(), request=_item_level_request(), now=NOW
        )

    assert conn.execute("SELECT count(*) FROM pinned").fetchone()[0] == 0


def _built(monkeypatch, **fields) -> LaunchRequest:
    conn, item = _create_conn(monkeypatch, status="idea")
    parsed = LaunchCreateRequest(
        project="launch-project",
        item=item,
        instructions="Custom full body.",
        compose_mandate=False,
        idempotency_key="built-key",
        **fields,
    )
    return launch_request_for_create(conn, parsed, project_id=10, deadline_seconds=600)


def test_a_named_level_on_an_item_carries_the_default_reason(monkeypatch) -> None:
    built = _built(monkeypatch, level="SENIOR")

    assert built.level == "SENIOR"
    assert built.level_reason == DEFAULT_LEVEL_REASON


def test_a_stated_reason_is_carried_verbatim(monkeypatch) -> None:
    built = _built(monkeypatch, level="SENIOR", level_reason="needs design judgment")

    assert built.level_reason == "needs design judgment"


@pytest.mark.parametrize(
    "selection",
    [{"use_stage_level": True}, {"executor_surface": "codex-cli"}],
    ids=["stage level", "exact selection"],
)
def test_an_item_launch_without_a_named_level_records_none(
    monkeypatch, selection
) -> None:
    built = _built(monkeypatch, **selection)

    assert built.level is None
    assert built.level_reason is None


def test_an_itemless_level_launch_records_none() -> None:
    parsed = LaunchCreateRequest(
        project="launch-project",
        level="SENIOR",
        instructions="Itemless body.",
        compose_mandate=False,
        idempotency_key="itemless-key",
    )

    built = launch_request_for_create(
        None, parsed, project_id=10, deadline_seconds=600, actor_id=None
    )

    assert built.item is None
    assert built.level == "SENIOR"
    assert built.level_reason is None


@pytest.mark.parametrize(
    "fields",
    [
        {"level_reason": "why"},
        {"level": "SENIOR", "level_reason": "why"},
        {"item": SEEDED_ITEM, "level_reason": "why"},
    ],
    ids=["neither", "no item", "no level"],
)
def test_a_level_reason_without_an_item_level_is_refused(fields) -> None:
    with pytest.raises(ValueError, match="level_reason_without_item_level"):
        LaunchCreateRequest(
            project="launch-project",
            executor_surface=None if "level" in fields else "codex-cli",
            instructions="body",
            compose_mandate=False,
            idempotency_key="reason-key",
            **fields,
        )
