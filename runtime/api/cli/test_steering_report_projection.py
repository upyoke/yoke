"""Steering report human and JSON projection contracts."""

import sys

from yoke_contracts.api.function_call import FunctionCallResponse


def test_report_delta_full_and_json_select_their_projection(monkeypatch, capsys):
    from yoke_cli.commands.adapters import steering_report

    captured = []

    def dispatch(**kwargs):
        captured.append(kwargs)
        if not kwargs["json_mode"]:
            response = FunctionCallResponse(
                success=True,
                function="steering.report.get",
                version="v1",
                result={"body": "complete report", "delta_body": "unchanged"},
            )
            kwargs["human_writer"](response, sys.stdout, sys.stderr)
        return 0

    monkeypatch.setattr(steering_report, "dispatch_and_emit", dispatch)
    for flags, payload, output in (
        ([], {"read_delta": True, "full": False}, "unchanged"),
        (["--full"], {"read_delta": True, "full": True}, "complete report"),
        (["--json"], {}, ""),
    ):
        assert steering_report.steering_report_get(flags) == 0
        assert captured[-1]["payload"] == payload
        assert capsys.readouterr().out.strip() == output
