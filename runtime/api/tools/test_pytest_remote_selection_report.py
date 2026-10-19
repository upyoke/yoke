"""A recorded CI wait tells the watching turn it may end."""

from __future__ import annotations

from yoke_core.tools import pytest_remote_selection_report as report

_RECORD = "yoke_core.domain.session_ci_wait_record.record_ci_run_wait"
_SESSION = "yoke_core.domain.session_ci_wait_record.ambient_session_id"


def _record(monkeypatch, *, session: str, warning: str = "") -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(_SESSION, lambda: session)
    monkeypatch.setattr(_RECORD, lambda **kw: calls.append(kw) or warning)
    report.record_wait(
        repo="acme/w",
        run_id="42",
        head_sha="a" * 40,
        continue_command="yoke watch pytest --impacted main --bounded",
    )
    return calls


def test_recorded_wait_says_end_the_turn(monkeypatch, capsys) -> None:
    calls = _record(monkeypatch, session="sess-1")

    assert calls[0]["run_id"] == "42"
    out = capsys.readouterr().out
    assert "ci wait recorded for run 42" in out
    assert "end the turn and do not poll GitHub" in out
    assert "`yoke watch pytest --impacted main --bounded`" in out


def test_refused_record_warns_and_promises_no_wake(monkeypatch, capsys) -> None:
    _record(monkeypatch, session="sess-1", warning="ci wait not recorded: down")

    out = capsys.readouterr().out
    assert "ci wait not recorded: down" in out
    assert "will not wake a stopped turn" in out
    assert "ci wait recorded" not in out


def test_no_session_records_and_prints_nothing(monkeypatch, capsys) -> None:
    calls = _record(monkeypatch, session="")

    assert calls == []
    assert capsys.readouterr().out == ""
