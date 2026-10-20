"""Ctrl-C coverage for the engine-owned ``yoke qa case run`` CLI."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import qa_case_execution_cli


def test_engine_cli_reports_cancellation_and_exits_130_on_ctrl_c(capsys) -> None:
    with mock.patch.object(
        qa_case_execution_cli, "execute_case", side_effect=KeyboardInterrupt
    ):
        code = qa_case_execution_cli.run(["--requirement-id", "41"])

    assert code == 130
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("yoke qa case run: cancelled:")
    assert "`yoke qa case run --requirement-id 41`" in captured.err
    assert "Traceback" not in captured.err
