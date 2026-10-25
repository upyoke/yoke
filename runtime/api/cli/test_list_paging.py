"""Long list reads keep complete JSON pages and bounded human summaries."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from yoke_cli.main import main
from yoke_cli.commands.adapters.list_paging import list_writer
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.list_paging import ListPageRequest, page_result

PREFIX = "APP"
REF = f"{PREFIX}-42"
LISTS = [
    (["qa", "requirement", "list", "--item", REF], "rows"),
    (["qa", "run", "list", "--requirement-id", "42"], "rows"),
    (["qa", "method", "list", "--project", "example"], "rows"),
    (["qa", "plan", "list", "--project", "example"], "rows"),
    (["qa", "activity", "list", "--project", "example"], "rows"),
    (["claims", "path", "list", "--item", REF], "claims"),
    (["items", "dependency", "list", REF], "dependencies"),
    (["item-worktrees", "list", REF], "worktrees"),
    (["item-worktrees", "inventory", "--project", "example"], "lanes"),
    (["epic-tasks", "list", "--epic", REF], "tasks"),
    (["strategy", "doc", "list", "--project", "example"], "docs"),
    (
        [
            "workflow-item",
            "epic-progress-note",
            "list",
            "--epic",
            REF,
            "--task-num",
            "1",
        ],
        "rows",
    ),
]


def run_list(monkeypatch, argv, key, *, legacy=False):
    requests = []
    rows = [
        dict(
            id=n,
            note_num=n,
            slug=str(n),
            task_num=n,
            title="界" * 10000,
            body="body\n|" * 10000,
            raw_result={"captured": "x" * 40000},
        )
        for n in range(61)
    ]

    def dispatch(request):
        requests.append(request)
        # The transport preserves the server's explicit page metadata.
        result = page_result({key: rows}, key, request.payload)
        if legacy:
            result.pop("offset", None)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
    out, err = io.StringIO(), io.StringIO()
    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=dispatch
    ):
        with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
    return code, out.getvalue(), err.getvalue(), requests


@pytest.mark.parametrize("argv,key", LISTS)
def test_default_list_is_bounded_and_teaches_continuation(monkeypatch, argv, key):
    code, out, err, requests = run_list(monkeypatch, argv, key)
    assert code == 0, err
    assert requests[-1].payload["limit"] == 25
    assert requests[-1].payload["offset"] == 0
    assert len(out.encode("utf-8")) < 28000
    assert "Next page: --offset 25" in out
    assert "Details:" in out


@pytest.mark.parametrize("argv,key", LISTS)
def test_json_pages_are_complete_and_reachable(monkeypatch, argv, key):
    found = []
    for offset in (0, 25, 50):
        code, out, err, _ = run_list(
            monkeypatch, [*argv, "--offset", str(offset), "--json"], key
        )
        assert code == 0, err
        result = json.loads(out)["result"]
        found.extend(row["id"] for row in result[key])
        assert result[key][0]["raw_result"]["captured"] == "x" * 40000
        assert result["next_offset"] == (offset + 25 if offset < 50 else None)
    assert found == list(range(61))


@pytest.mark.parametrize("argv,key", LISTS)
def test_full_expands_only_requested_page(monkeypatch, argv, key):
    code, out, err, requests = run_list(
        monkeypatch, [*argv, "--limit", "1", "--offset", "60", "--full", "--json"], key
    )
    assert code == 0, err
    assert requests[-1].payload["limit"] == 1
    result = json.loads(out)["result"]
    assert [row["id"] for row in result[key]] == [60]
    assert result["next_offset"] is None


@pytest.mark.parametrize("argv,key", LISTS)
def test_invalid_page_inputs_are_usage_errors(monkeypatch, argv, key):
    code, _, _, requests = run_list(monkeypatch, [*argv, "--offset", "-1"], key)
    assert code == 2
    assert not requests


def test_byte_bound_continues_after_last_printed_row():
    rows = [
        {
            field: "界" * 10000
            for field in (
                "direction",
                "other_item",
                "gate_point",
                "satisfaction",
                "rationale",
            )
        }
        for _ in range(500)
    ]
    response = SimpleNamespace(
        result={"dependencies": rows, "offset": 7, "next_offset": 507}
    )
    out = io.StringIO()
    list_writer("items.dependency.list")(response, out, io.StringIO())
    text = out.getvalue()
    served = len([line for line in text.splitlines() if line.startswith("界")])
    assert 0 < served < 500
    assert f"Next page: --offset {7 + served}" in text
    assert "…" in text
    assert len(text.encode("utf-8")) < 28000


@pytest.mark.parametrize("payload", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_server_rejects_invalid_page(payload):
    with pytest.raises(ValidationError):
        ListPageRequest.model_validate(payload)


def test_empty_and_past_end_pages_have_no_continuation():
    for rows in ([], [{"id": 1}]):
        result = page_result(
            {"rows": rows, "current_run_id": 1}, "rows", {"limit": 25, "offset": 99}
        )
        assert result["rows"] == []
        assert result["next_offset"] is None
        assert result["current_run_id"] == 1


def test_older_server_cannot_silently_repeat_an_offset_page(monkeypatch):
    argv, key = LISTS[0]
    code, out, err, _ = run_list(
        monkeypatch, [*argv, "--offset", "25"], key, legacy=True
    )
    assert code == 1
    assert "list_paging_unavailable" in err
    assert "next-release" in err
    assert "Upgrade the control plane" in err
    assert " | " not in out
