"""Default launch pages fit while preserving IDs, history and explicit detail."""

import io
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_launch_list as adapter
from yoke_cli.transport.output_limit import read_output_scope


def _page():
    def row(n):
        return {
            "launch_id": f"00000000-0000-0000-0000-{n:012}",
            "state": "succeeded", "result_code": "registered",
            "project": "example", "item": "APP-7", "selected_surface": "codex-cli",
            "requested_surface": "codex-cli", "resolved_model": "example-model",
            "assigned_machine_id": "10000000-0000-0000-0000-000000000000",
            "registered_session_id": "20000000-0000-0000-0000-000000000000",
            "created_at": "2026-01-01T12:00:00Z",
        }
    return {"operational": [row(n) for n in range(50)],
            "history": [row(n) for n in range(50, 100)],
            "history_matched_count": 120, "next_cursor": "history-cursor"}


def _render(monkeypatch, args):
    calls = []
    out = io.StringIO()

    def dispatch(**kwargs):
        calls.append(kwargs)
        kwargs["human_writer"](SimpleNamespace(result=_page()), out, io.StringIO())
        return 0

    monkeypatch.setattr(adapter, "dispatch_and_emit", dispatch)
    with read_output_scope(args, "session_control.launch.list"):
        assert adapter.session_launch_list(args) == 0
    return out.getvalue(), calls[0]


def test_default_launch_page_fits_with_operational_and_history_rows(monkeypatch):
    text, call = _render(monkeypatch, ["--project", "example"])
    assert len(text.encode()) < 28_000
    assert call["payload"] == {"project": "example", "limit": 50}
    for row in [*_page()["operational"], *_page()["history"]]:
        assert row["launch_id"] in text
    assert "APP-7" in text and "codex-cli" in text
    assert "COMPLETED HISTORY (50 of 120 matching)" in text
    assert "--cursor history-cursor" in text and "--full" in text
    assert "REGISTERED" not in text and "MACHINE" not in text


def test_full_launch_list_retains_detail_columns(monkeypatch):
    text, _ = _render(monkeypatch, ["--project", "example", "--full"])
    assert "REGISTERED" in text and "MACHINE" in text and "MODEL" in text
    assert "20000000-0000-0000-0000-000000000000" in text
