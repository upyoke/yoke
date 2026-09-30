"""Projected flow values render source labels in the public item reader."""

from io import StringIO
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import items


@pytest.mark.parametrize(
    "source, value, expected",
    [
        ("item", "pinned-flow", "pinned-flow (item)"),
        ("project_default", "default-flow", "default-flow (project default)"),
        ("unreadable", "", "no completion flow (unreadable)"),
    ],
)
def test_get_flow_human_output(monkeypatch, source, value, expected):
    stdout = StringIO()
    monkeypatch.setattr(items, "item_target", lambda *args: None)

    def dispatch(**kwargs):
        kwargs["human_writer"](
            SimpleNamespace(
                success=True,
                result={
                    "fields": {"deployment_flow": {"value": value, "source": source}}
                },
            ),
            stdout,
            StringIO(),
        )
        return 0

    monkeypatch.setattr(items, "dispatch_and_emit", dispatch)
    assert items.items_get([f"YOK-{9800}", "deployment_flow"]) == 0
    assert stdout.getvalue().strip() == expected
