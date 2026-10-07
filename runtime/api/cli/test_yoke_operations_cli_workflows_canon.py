"""CLI adapters for listing, previewing, taking, and following canon updates."""

from __future__ import annotations

import sys
from unittest.mock import patch

from yoke_cli.commands.adapters.workflows_canon import (
    workflows_canon_follow_set,
    workflows_canon_status_list,
    workflows_canon_update_apply,
    workflows_canon_update_apply_all,
    workflows_canon_update_preview,
)
from yoke_cli.commands.registry_workflows import WORKFLOW_SUBCOMMAND_REGISTRY
from yoke_contracts.api.function_call import FunctionCallResponse

_DISPATCH = "yoke_cli.commands.adapters.workflows_canon.dispatch_and_emit"


def _run(adapter, args, function_id, result, *, json_mode=False):
    """Run *adapter* against a canned response; return (rc, captured call)."""
    response = FunctionCallResponse(
        success=True, function=function_id, version="v1", result=result,
    )
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        recovery = kwargs.get("response_recovery")
        if recovery is not None:
            recovery(response, None)
        if not json_mode:
            kwargs["human_writer"](response, sys.stdout, sys.stderr)
        return 0

    with patch(_DISPATCH, side_effect=_dispatch):
        rc = adapter(args)
    return rc, captured


def test_every_canon_command_is_registered_against_its_function_id():
    expected = {
        ("workflows", "canon-status", "list"): "workflows.canon_status.list",
        ("workflows", "canon-update", "preview"): "workflows.canon_update.preview",
        ("workflows", "canon-update", "apply"): "workflows.canon_update.apply",
        ("workflows", "canon-update", "apply-all"): (
            "workflows.canon_update.apply_all"
        ),
        ("workflows", "canon-follow", "set"): "workflows.canon_follow.set",
    }
    for path, function_id in expected.items():
        assert WORKFLOW_SUBCOMMAND_REGISTRY[path][0] == function_id


def test_status_list_pending_narrows_and_prints_the_expected_version(capsys):
    rc, call = _run(
        workflows_canon_status_list, ["--pending"],
        "workflows.canon_status.list",
        {"rows": [{
            "workflow_id": "issue", "current_version": 4,
            "state": "update_available", "follow": "manual",
            "latest_canon_version": 3, "pending": True,
        }]},
    )

    assert rc == 0
    assert call["payload"] == {"pending_only": True}
    assert capsys.readouterr().out.splitlines() == [
        "workflow-canon|issue|current_version=4|update_available|"
        "follow=manual|latest_canon_version=3|pending=true",
    ]


def test_an_empty_pending_list_says_so(capsys):
    _run(workflows_canon_status_list, ["--pending"],
         "workflows.canon_status.list", {"rows": []})

    assert capsys.readouterr().out.strip() == (
        "no workflow has a pending published update"
    )


def test_preview_prints_taken_kept_and_names_conflicts(capsys):
    rc, call = _run(
        workflows_canon_update_preview, ["issue"],
        "workflows.canon_update.preview",
        {
            "workflow_id": "issue", "state": "customized_update_available",
            "derived_from_canon_version": 2, "latest_canon_version": 3,
            "clean": False, "taken": ["stages[0].label"],
            "kept": ["policies.qa"], "conflicts": [{"path": "stages[1].gates"}],
            "definition": {},
        },
    )

    assert rc == 0
    assert call["payload"] == {"workflow_id": "issue"}
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "workflow-canon-preview|issue|customized_update_available|"
        "derived_from_canon_version=2|latest_canon_version=3|clean=false",
        "taken|issue|stages[0].label",
        "kept|issue|policies.qa",
        "conflict|issue|stages[1].gates",
    ]
    assert "will refuse to apply" in captured.err


def test_apply_receipt_shows_the_move_and_what_changed(capsys):
    rc, call = _run(
        workflows_canon_update_apply,
        ["issue", "--expected-current-version", "4"],
        "workflows.canon_update.apply",
        {
            "workflow_id": "issue", "version": 5, "version_id": 51,
            "definition_digest": "abc", "canon_version": 3,
            "taken": ["stages[0].label"], "kept": [],
        },
    )

    assert rc == 0
    assert call["payload"] == {
        "workflow_id": "issue", "expected_current_version": 4,
    }
    assert capsys.readouterr().out.splitlines() == [
        "workflow-canon-update-applied|issue|from_version=4|to_version=5|"
        "canon_version=3|abc",
        "taken|issue|stages[0].label",
    ]


def test_apply_all_builds_entries_and_fails_loudly_on_a_refusal(capsys):
    rc, call = _run(
        workflows_canon_update_apply_all, ["issue=4", "epic=7"],
        "workflows.canon_update.apply_all",
        {
            "applied": [{
                "workflow_id": "issue", "version": 5, "version_id": 51,
                "definition_digest": "abc", "canon_version": 3,
                "taken": [], "kept": [],
            }],
            "refused": [{
                "workflow_id": "epic", "code": "incompatible",
                "message": "this update conflicts with local edits at: x",
            }],
        },
    )

    assert call["payload"] == {"workflows": [
        {"workflow_id": "issue", "expected_current_version": 4},
        {"workflow_id": "epic", "expected_current_version": 7},
    ]}
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "workflow-canon-update-applied|issue|from_version=4|to_version=5|"
        "canon_version=3|abc",
        "workflow-canon-update-refused|epic|incompatible|"
        "this update conflicts with local edits at: x",
    ]
    assert "yoke workflows canon-update preview epic" in captured.err
    assert "1 of 2 workflow update(s) refused" in captured.err


def test_apply_all_refusal_exits_non_zero_in_json_mode_too():
    rc, _call = _run(
        workflows_canon_update_apply_all, ["epic=7", "--json"],
        "workflows.canon_update.apply_all",
        {"applied": [], "refused": [
            {"workflow_id": "epic", "code": "not_found", "message": "m"},
        ]},
        json_mode=True,
    )

    assert rc == 1


def test_apply_all_rejects_a_malformed_entry_before_dispatch(capsys):
    with patch(_DISPATCH) as dispatch:
        rc = workflows_canon_update_apply_all(["issue"])

    assert rc != 0
    dispatch.assert_not_called()
    assert "expected WORKFLOW=VERSION" in capsys.readouterr().err


def test_follow_receipt_shows_the_previous_setting(capsys):
    rc, call = _run(
        workflows_canon_follow_set, ["issue", "auto"],
        "workflows.canon_follow.set",
        {"workflow_id": "issue", "follow": "auto", "previous_follow": "manual"},
    )

    assert rc == 0
    assert call["payload"] == {"workflow_id": "issue", "follow": "auto"}
    assert capsys.readouterr().out.strip() == (
        "workflow-canon-follow|issue|manual->auto"
    )
