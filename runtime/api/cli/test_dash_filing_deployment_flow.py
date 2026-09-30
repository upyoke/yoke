"""``yoke dash --deployment-flow`` chooses the completion flow at filing.

A Dash filed without one takes the project default, and learning that the
release carrying it runs a different flow happened only at composition --
after the merge, when the recovery was reconciling the item's flow by hand.
Naming it at filing puts the choice where it is cheapest; the create path
validates it against the project's registered flows.
"""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import dash_file


def _capture(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(dash_file, "dispatch_and_emit", _dispatch)
    return captured


def test_dash_filing_sends_the_named_deployment_flow(monkeypatch):
    captured = _capture(monkeypatch)

    assert (
        dash_file.dash_file(
            [
                "Tighten footer",
                "Fix the footer copy.",
                "--deployment-flow",
                "yoke-hosted-production-release-qa",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "items.create"
    assert captured["payload"]["deployment_flow"] == (
        "yoke-hosted-production-release-qa"
    )


def test_dash_filing_without_a_flow_leaves_the_project_default(monkeypatch):
    captured = _capture(monkeypatch)

    assert dash_file.dash_file(["Tighten footer", "Fix the footer copy."]) == 0

    assert "deployment_flow" not in captured["payload"]


def test_dash_filing_help_teaches_the_flow_choice(capsys):
    with pytest.raises(SystemExit):
        dash_file.dash_file(["--help"])

    help_text = capsys.readouterr().out
    assert "--deployment-flow FLOW" in help_text
    assert "yoke deployment-flows list" in help_text
