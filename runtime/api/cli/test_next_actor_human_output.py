"""Default human displays omit next actor while explicit and JSON reads retain it."""

import io
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import frontier_read, listing
from yoke_cli.commands.adapters.item_flow_output import compact_item_result
from yoke_cli.config.status_render import dumps_json, render_human


NEXT = {"actor": "operator", "reason": "decision_required"}


@pytest.mark.parametrize("args", [[], ["--json"], ["--fields", "id,next_actor"]])
def test_item_listing_preserves_explicit_and_json_reads(monkeypatch, args):
    result = {"fields": ["id", "next_actor"], "rows": [{"id": "item", "next_actor": NEXT}]}
    observed = {}

    def dispatch(**kwargs):
        observed.update(kwargs)
        if not kwargs["json_mode"]:
            output = io.StringIO()
            kwargs["human_writer"](SimpleNamespace(result=result), output, io.StringIO())
            observed["text"] = output.getvalue()
        return 0

    monkeypatch.setattr(listing, "dispatch_and_emit", dispatch)
    monkeypatch.setattr(listing, "client_project_context", lambda _: "project")
    assert listing.items_list(args) == 0
    assert result["rows"][0]["next_actor"] == NEXT
    if "--fields" in args:
        assert "next actor" in observed["text"]
        assert observed["payload"]["fields"] == ["id", "next_actor"]
    elif "--json" in args:
        assert "fields" not in observed["payload"]
    else:
        assert "next actor" not in observed["text"]
        assert "decision_required" not in observed["text"]


def test_frontier_human_projection_keeps_source_intact(monkeypatch):
    result = {"ready": [{"public_ref": "item", "next_actor": NEXT}]}
    output = io.StringIO()

    def dispatch(**kwargs):
        kwargs["human_writer"](SimpleNamespace(result=result), output, io.StringIO())
        return 0

    monkeypatch.setattr(frontier_read, "dispatch_and_emit", dispatch)
    assert frontier_read.frontier_list([]) == 0
    assert "next actor" not in output.getvalue()
    assert result["ready"][0]["next_actor"] == NEXT


def test_default_and_full_item_human_reads_omit_next_actor():
    result = {"fields": {"title": "Item", "next_actor": NEXT}}
    for full in (False, True):
        assert "next_actor" not in str(compact_item_result(result, "item", full=full))
    assert result["fields"]["next_actor"] == NEXT


def test_status_json_retains_both_session_and_item_next_actor():
    report = {"session": {"presence": "present", "next_actor": NEXT},
              "item_state": {"stage": "implementing", "next_actor": NEXT}}
    assert "next_actor" not in render_human(report)
    assert dumps_json(report).count('"next_actor"') == 2
