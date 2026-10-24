"""An item preview sends only the item; help teaches the default route first."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands.adapters import session_control_launches as launches


def _capture_dispatch(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(launches, "dispatch_and_emit", _dispatch)
    return calls


def test_an_item_preview_without_selectors_sends_only_the_item(monkeypatch):
    calls = _capture_dispatch(monkeypatch)

    assert launches.session_launch_preview(["--project", "yoke", "--item", "YOK-7"]) == 0
    assert calls[0]["function_id"] == "session_control.launch.preview"
    assert calls[0]["payload"] == {"project": "yoke", "item": "YOK-7"}


def test_an_item_preview_keeps_a_machine_override(monkeypatch):
    calls = _capture_dispatch(monkeypatch)

    args = ["--project", "yoke", "--item", "YOK-7", "--machine", "m-1"]
    assert launches.session_launch_preview(args) == 0
    assert calls[0]["payload"] == {
        "project": "yoke",
        "item": "YOK-7",
        "machine_id": "m-1",
    }


def test_an_item_preview_with_a_level_override_sends_both(monkeypatch):
    calls = _capture_dispatch(monkeypatch)

    args = ["--project", "yoke", "--item", "YOK-7", "--level", "junior"]
    assert launches.session_launch_preview(args) == 0
    assert calls[0]["payload"] == {"project": "yoke", "level": "junior", "item": "YOK-7"}


def test_an_item_preview_with_a_model_but_no_surface_is_refused(monkeypatch, capsys):
    calls = _capture_dispatch(monkeypatch)

    args = ["--project", "yoke", "--item", "YOK-7", "--model", "gpt-6.1-sol"]
    assert launches.session_launch_preview(args) == 2
    assert calls == []
    refusal = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert refusal["message"].startswith("launch_selection_missing")


def test_sessions_create_preview_accepts_an_item(monkeypatch):
    calls = _capture_dispatch(monkeypatch)

    args = ["--project", "yoke", "--item", "YOK-7", "--preview"]
    assert launches.sessions_create(args) == 0
    assert calls[0]["function_id"] == "session_control.launch.preview"
    assert calls[0]["payload"] == {"project": "yoke", "item": "YOK-7"}


@pytest.mark.parametrize(
    "command", [launches.session_launch_create, launches.session_launch_preview]
)
def test_help_states_the_default_then_shows_default_level_and_placement(
    command, capsys
):
    with pytest.raises(SystemExit):
        command(["--help"])
    help_text = capsys.readouterr().out
    flat = " ".join(help_text.split())

    assert flat.index("Omit selection flags: Yoke routes by the item's workflow") < (
        flat.index("options:")
    )
    examples = help_text[help_text.index("examples:") :]
    default = examples.index("Default:")
    level = examples.index("Level override:")
    placement = examples.index("Placement override:")
    assert default < level < placement
    default_line = examples[default:level].splitlines()[1]
    assert "--level" not in default_line and "--surface" not in default_line
    assert "Override: use this surface" in flat
    assert "Override: place on this registered Machine id" in flat
