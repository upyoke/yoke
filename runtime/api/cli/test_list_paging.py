"""Long list reads keep complete rows, explicit continuation, and shared overflow recovery."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from yoke_cli.main import main
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


def run_list(monkeypatch, argv, key, *, large=False):
    requests = []
    rows = [
        dict(
            id=n,
            note_num=n,
            slug=str(n),
            task_num=n,
            title="界" * (10000 if large else 3),
            body="body\n|" * (10000 if large else 2),
            raw_result={"captured": "x" * (40000 if large else 4)},
        )
        for n in range(61)
    ]

    def dispatch(request):
        requests.append(request)
        # The transport preserves the server's explicit page metadata.
        result = page_result({key: rows}, key, request.payload)
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
def test_default_list_teaches_continuation(monkeypatch, argv, key):
    code, out, err, requests = run_list(monkeypatch, argv, key)
    assert code == 0, err
    assert requests[-1].payload["limit"] == 25
    assert requests[-1].payload["offset"] == 0
    assert len(out.encode("utf-8")) < 28000
    assert "More rows. Next page:" in out
    assert "--offset 25" in out


@pytest.mark.parametrize("argv,key", LISTS)
def test_json_pages_are_complete_and_reachable(monkeypatch, argv, key):
    found = []
    for offset in (0, 25, 50):
        code, out, err, _ = run_list(
            monkeypatch, [*argv, "--offset", str(offset), "--json"], key, large=True
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


def test_large_default_page_uses_shared_overflow_recovery(monkeypatch):
    argv, key = LISTS[0]
    code, out, err, _ = run_list(monkeypatch, argv, key, large=True)
    assert code != 0
    assert "read_output_limit_exceeded" in err
    assert "--limit" in err
    assert "--full" in err
    assert out == ""


def test_next_page_command_keeps_filters_and_replaces_offset(monkeypatch):
    argv, key = LISTS[0]
    code, out, err, _ = run_list(monkeypatch, [*argv, "--offset", "25"], key)
    assert code == 0, err
    next_line = next(line for line in out.splitlines() if "Next page:" in line)
    assert f"--item {REF}" in next_line
    assert "--offset 50" in next_line
    assert "--offset 25" not in next_line


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


@pytest.mark.parametrize(
    "argv,key",
    [
        (["sessions", "list", "--project", "example"], "rows"),
        (["ouroboros", "field-note", "list", "--project", "example"], "entries"),
        (
            [
                "events",
                "performance",
                "detail",
                "--since",
                "2026-01-01T00:00:00Z",
                "--until",
                "2026-01-02T00:00:00Z",
            ],
            "rows",
        ),
    ],
)
def test_existing_paged_commands_keep_page_arguments_and_continuation(
    monkeypatch, argv, key
):
    code, out, err, requests = run_list(
        monkeypatch, [*argv, "--limit", "2", "--offset", "1"], key
    )
    assert code == 0, err
    assert requests[-1].payload["limit"] == 2
    assert requests[-1].payload["offset"] == 1
    next_line = next(line for line in out.splitlines() if "Next page:" in line)
    assert "--offset 3" in next_line
    if "--project" in argv:
        assert "--project example" in next_line
