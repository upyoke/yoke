"""A mandatory conflict survey gates worktree preparation, with advisory overlaps."""

import json
from types import SimpleNamespace
from yoke_core.domain import direct_workflow_worktree_preflight as preflight


def _run_preflight_status(monkeypatch, capsys, status):
    def _dispatch(*, function_id, target, **_kwargs):
        if function_id == "items.detail.get":
            item = (
                {"public_ref": "YOK-2290", "workflow": {"id": "dash"}}
                if target.public_ref == "YOK-2290"
                else {"id": 2291, "public_ref": "YOK-2291"}
            )
            result = {"item": item}
        else:
            assert function_id == "direct_workflow.conflict_survey.status"
            result = status
        return SimpleNamespace(success=True, result=result, error=None)

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatch,
    )
    prepared = []

    def _prepare(**kwargs):
        prepared.append(kwargs)
        return SimpleNamespace(ok=True, to_envelope=lambda: {"ok": True})

    monkeypatch.setattr(preflight, "run_preflight", _prepare)
    rc = preflight.run(["YOK-2290", "--workflow", "dash"])
    return rc, json.loads(capsys.readouterr().out), prepared


def test_worktree_preflight_reports_survey_advisory_and_proceeds(monkeypatch, capsys):
    blocker = {
        "kind": "survey_scope",
        "owner_public_ref": "YOK-2291",
        "path": "src/shared.py",
        "state": "implementing",
    }
    rc, payload, prepared = _run_preflight_status(
        monkeypatch,
        capsys,
        {"found": True, "clear": False, "blockers": [blocker]},
    )

    assert rc == 0 and len(prepared) == 1
    advisory = payload["advisories"][0]
    assert advisory["public_ref"] == "YOK-2291"
    assert advisory["status"] == "implementing"
    assert advisory["shared_paths"] == ["src/shared.py"]
    assert "Proceed" in advisory["routes"]["proceed"]
    assert "yield" in advisory["routes"]


def test_worktree_preflight_still_refuses_missing_survey(monkeypatch, capsys):
    rc, payload, prepared = _run_preflight_status(
        monkeypatch,
        capsys,
        {"found": False},
    )
    assert rc == 1 and prepared == []
    assert payload["block_kind"] == "conflict-survey-missing"
