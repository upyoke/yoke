"""Transport-aware routing regression tests for the post-done cascade reads.

The done-transition post-merge epic cascade reads (the epic task listing and
each cascaded task's ``github_issue``) must route through ``call_dispatcher``
so the cascade runs over an https control plane. These tests monkeypatch
``call_dispatcher`` and assert the reads relay instead of opening a bare
``_connect()``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition as dt
from yoke_core.engines import done_transition_status as status


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _install(monkeypatch, fake):
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fake
    )
    monkeypatch.setattr(status, "call_dispatcher", fake)
    monkeypatch.setattr(
        dt, "_connect",
        lambda *a, **k: pytest.fail("must not open a bare _connect() on a read path"),
    )


class TestEpicTaskListRelay:
    def test_empty_listing_relays_and_skips(self, monkeypatch, capsys):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("done_transition.epic_task_list", {"task_list": ""})

        _install(monkeypatch, fake)
        status._cascade_epic_tasks_to_done(8600, public_ref="YOK-8600")
        assert calls[0]["function_id"] == "done_transition.epic_task_list"
        assert calls[0]["payload"] == {"epic_id": "8600"}
        assert "No tasks to cascade." in capsys.readouterr().out


class TestGithubIssuesRelay:
    def test_batch_sync_relays_github_issues(self, monkeypatch, capsys):
        monkeypatch.setattr(
            status, "resolve_project_github_auth",
            lambda *a, **k: SimpleNamespace(repo="org/repo", token="tok"),
        )
        monkeypatch.setattr(status, "request_with_retry", lambda *a, **k: None)
        monkeypatch.setattr(
            "yoke_core.domain.project_label_policy.get_color",
            lambda *a, **k: "C5DEF5",
        )
        seen = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            seen.append(fid)
            if fid == "done_transition.item_field":
                return _resp(fid, {"value": "yoke"})
            if fid == "done_transition.epic_task_github_issues":
                assert kwargs["payload"] == {"epic_id": "8600", "task_nums": ["1"]}
                return _resp(fid, {"github_issues": {"1": "#701"}})
            return _resp(fid)

        _install(monkeypatch, fake)
        status._batch_github_sync_tasks(8600, ["1"], public_ref="YOK-8600")
        assert "done_transition.epic_task_github_issues" in seen
        assert "GitHub: #701" in capsys.readouterr().out
