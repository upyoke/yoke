"""Curate reads compact evidence pages without losing machine data."""

import json

import pytest

from yoke_cli.commands.adapters import feedback, list_paging
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse


def _page():
    return {"entries": [
        {"id": n, "category": "failed", "timestamp": "2026-01-01T12:00:00Z",
         "body": f"Evidence {n}: " + "長い evidence\n" * 400,
         "reporter_email": "reporter@example.test", "project": "example",
         "promoted_dash": None}
        for n in range(1, 51)
    ], "next_offset": 50, "limit": 50, "offset": 0}


def _run(monkeypatch, args, result):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return emit_response(
            FunctionCallResponse(success=True, function=kwargs["function_id"],
                                 version="v1", result=result),
            json_mode=kwargs["json_mode"], human_writer=kwargs["human_writer"],
        )

    monkeypatch.setattr(list_paging, "dispatch_and_emit", dispatch)
    monkeypatch.setattr(feedback, "client_project_context", lambda project: "example")
    with read_output_scope(args, "ouroboros.field_note.list"):
        code = feedback.feedback_list(args)
    return code, calls[0]


def test_curate_page_has_fifty_compact_rows_under_output_cap(monkeypatch, capsys):
    code, call = _run(monkeypatch, ["--unreviewed", "--scope", "universe",
                                  "--limit", "50", "--offset", "0"], _page())
    captured = capsys.readouterr()
    assert code == 0 and not captured.err
    assert len(captured.out.encode()) < REPLY_LIMIT_BYTES
    rows = [line for line in captured.out.splitlines() if " | failed | " in line]
    assert len(rows) == 50
    for n, line in enumerate(rows, 1):
        assert line.startswith(f"{n} | failed | 2026-01-01T12:00:00Z | Evidence {n}:")
        assert line.endswith("...")
    assert "yoke feedback get ID" in captured.out
    assert "More rows. Next page:" in captured.out
    assert call["payload"] == {"scope": "universe", "unreviewed": True,
                               "project": "example", "limit": 50, "offset": 0}


def test_json_preserves_complete_page(monkeypatch, capsys):
    page = _page()
    code, _ = _run(monkeypatch, ["--json"], page)
    assert code == 0
    assert json.loads(capsys.readouterr().out)["result"] == page


@pytest.mark.parametrize("result, expected", [
    ({"entries": [], "count": 26743}, "Matching feedback: 26743"),
    ({"entries": []}, "Feedback (0 rows)"),
])
def test_count_and_empty_pages_are_explicit(monkeypatch, capsys, result, expected):
    code, _ = _run(monkeypatch, [], result)
    assert code == 0
    assert expected in capsys.readouterr().out
