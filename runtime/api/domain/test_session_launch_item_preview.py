"""An item preview takes the route an item-bound create takes."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.models import LaunchPreviewRequest
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_requests import create_launch

from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_handler_deadlines import (
    _request,
    _wire_handler,
)
from runtime.api.domain.test_workflow_stage_launches import staged_launch


def _preview(monkeypatch, conn, payload: dict):
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_preview_payload.utc_now",
        lambda: parse_instant(NOW),
    )
    return handlers.handle_launch_preview(
        _request("session_control.launch.preview", {"project": "p", **payload})
    )


def test_an_item_preview_matches_what_the_item_create_selects(monkeypatch):
    conn, request = staged_launch(monkeypatch)

    outcome = _preview(monkeypatch, conn, {"item": request.item})

    assert outcome.primary_success, outcome.error
    preview = outcome.result_payload
    launch = create_launch(conn, auth=authorization(), request=request, now=NOW).launch
    assert preview["item"] == request.item
    assert preview["requested_level"] == launch.requested_level == "JUNIOR"
    assert preview["model"] == launch.resolved_model
    assert preview["launchable"] is True


def test_a_level_beside_the_item_overrides_its_stage_level(monkeypatch):
    conn, request = staged_launch(monkeypatch)

    outcome = _preview(monkeypatch, conn, {"item": request.item, "level": "SENIOR"})

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["requested_level"] == "SENIOR"


def test_an_item_outside_the_project_is_refused_by_name(monkeypatch):
    conn, _request_ = staged_launch(monkeypatch)

    outcome = _preview(monkeypatch, conn, {"item": "NOPE-404"})

    assert not outcome.primary_success
    assert outcome.error.code == "item_not_found"


def test_an_item_alone_is_a_complete_preview_selection():
    assert LaunchPreviewRequest(project="yoke", item="YOK-1").level is None


def test_an_item_with_model_knobs_but_no_surface_is_refused():
    with pytest.raises(ValueError, match="launch_selection_missing"):
        LaunchPreviewRequest(project="yoke", item="YOK-1", model="gpt-6.1-sol")
