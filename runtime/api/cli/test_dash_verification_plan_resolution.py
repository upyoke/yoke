"""Dash filing resolves plan slugs and accepts JSON worktree preparation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import dash_file, dash_verification_plan
from yoke_cli.commands import direct_workflow_worktree
from yoke_core.api import service_client_structured_api_adapter
from yoke_core.domain import direct_workflow_worktree_preflight


def _plan_roster(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> dict:
    lookup: dict = {}

    def _call_dispatcher(**kwargs):
        lookup.update(kwargs)
        return SimpleNamespace(success=True, result={"rows": rows}, error=None)

    monkeypatch.setattr(
        dash_verification_plan._helpers,
        "ensure_handlers_loaded",
        lambda: None,
    )
    monkeypatch.setattr(
        dash_verification_plan,
        "call_dispatcher",
        _call_dispatcher,
    )
    return lookup


def _capture_filing(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(dash_file, "dispatch_and_emit", _dispatch)
    return captured


def test_dash_filing_resolves_plan_slug_within_item_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = _plan_roster(
        monkeypatch,
        [{"id": 38, "slug": "registered-command-quick", "name": "Quick"}],
    )
    captured = _capture_filing(monkeypatch)

    assert (
        dash_file.dash_file(
            [
                "Title",
                "Instruction",
                "--project",
                "yoke",
                "--verification-plan",
                "registered-command-quick",
                "--json",
            ]
        )
        == 0
    )

    assert lookup["function_id"] == "qa.plan.list"
    assert lookup["payload"] == {"project": "yoke"}
    assert captured["payload"]["workflow_posture"]["verification"] == {
        "kind": "plan",
        "plan_id": 38,
    }


def test_dash_filing_keeps_integer_plan_id_without_catalog_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dash_verification_plan,
        "call_dispatcher",
        lambda **_: pytest.fail("integer ids must not perform a slug lookup"),
    )
    captured = _capture_filing(monkeypatch)

    assert dash_file.dash_file(["Title", "Instruction", "--verification-plan", "38"]) == 0
    assert captured["payload"]["workflow_posture"]["verification"]["plan_id"] == 38


def test_unknown_plan_slug_names_slug_and_project(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _plan_roster(monkeypatch, [])

    assert (
        dash_file.dash_file(
            [
                "Title",
                "Instruction",
                "--project",
                "external",
                "--verification-plan",
                "missing-plan",
            ]
        )
        == 2
    )

    error = capsys.readouterr().err
    assert "missing-plan" in error
    assert "external" in error


def test_ambiguous_plan_slug_lists_every_candidate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _plan_roster(
        monkeypatch,
        [
            {"id": 38, "slug": "quick", "name": "Quick A"},
            {"id": 41, "slug": "quick", "name": "Quick B"},
        ],
    )

    assert (
        dash_file.dash_file(
            [
                "Title",
                "Instruction",
                "--project",
                "yoke",
                "--verification-plan",
                "quick",
            ]
        )
        == 2
    )

    error = capsys.readouterr().err
    assert "ambiguous" in error
    assert "id=38" in error
    assert "id=41" in error


def test_worktree_prepare_accepts_json_and_emits_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _call_dispatcher(*, function_id, **_kwargs):
        if function_id == "items.detail.get":
            return SimpleNamespace(
                success=True,
                result={"item": {"id": 9, "workflow": {"id": "dash"}}},
                error=None,
            )
        if function_id == "direct_workflow.conflict_survey.status":
            return SimpleNamespace(
                success=True,
                result={
                    "found": True,
                    "clear": True,
                    "touch_paths": ["pkg/file.py"],
                    "integration_target": "main",
                },
                error=None,
            )
        pytest.fail(f"unexpected function {function_id}")

    monkeypatch.setattr(
        service_client_structured_api_adapter,
        "call_dispatcher",
        _call_dispatcher,
    )
    monkeypatch.setattr(
        direct_workflow_worktree_preflight,
        "run_preflight",
        lambda **_: SimpleNamespace(
            ok=True,
            to_envelope=lambda: {"ok": True, "worktree_path": "/lane"},
        ),
    )

    assert (
        direct_workflow_worktree_preflight.run(
            ["YOK-9", "--workflow", "dash", "--json"]
        )
        == 0
    )

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    assert envelope["worktree_path"] == "/lane"
    assert "run_recipes" in envelope


def test_worktree_prepare_still_rejects_unknown_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        direct_workflow_worktree_preflight.run(
            ["YOK-9", "--workflow", "dash", "--not-a-real-flag"]
        )

    assert raised.value.code == 2
    assert "unrecognized arguments: --not-a-real-flag" in capsys.readouterr().err
    assert "[--json]" in direct_workflow_worktree.PREPARE_USAGE
