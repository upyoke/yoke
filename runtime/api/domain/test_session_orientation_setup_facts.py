"""All harness composers preserve setup facts and required context budgets."""

from pathlib import Path

import pytest
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain import session_orientation as orientation
from yoke_core.domain import global_orientation
from yoke_core.domain.session_orientation_setup import render_with_setup


@pytest.mark.parametrize("budget", INLINE_CONTEXT_BYTES.values())
def test_setup_collapses_before_optional_git_context(budget):
    rendered = render_with_setup(
        ["Required identity"],
        [["branch"], []],
        ["Required startup"],
        ["Setup: " + "長" * budget],
        budget,
    )
    assert "Setup: run yoke onboard checklist get" in rendered
    assert "branch" in rendered
    assert "Required startup" in rendered
    assert len(rendered.encode()) <= budget


def test_project_delivery_contains_one_setup_summary(monkeypatch):
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "")
    monkeypatch.setattr(
        orientation, "_startup_block_lines", lambda: ["Required startup"]
    )
    body = orientation.render_orientation(
        {
            "session_id": "session",
            "_yoke_setup_lines": [
                "Setup: unknown checkout-binding",
                "Next: yoke setup --agent",
            ],
        },
        Path("/external"),
    )
    assert body.count("Setup:") == body.count("Next:") == 1
    assert "Required startup" in body
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())


def test_global_has_machine_context_without_project_homes(monkeypatch):
    monkeypatch.setattr(global_orientation, "_project_folders", lambda: [])
    body = global_orientation.render_global_orientation(
        "session",
        Path("/outside"),
        setup_lines=["Setup: 3 configured", "Next: use yoke-global"],
    )
    assert "Setup: 3 configured" in body
    assert ".yoke/docs" not in body
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_source_composers_use_same_summary(monkeypatch, harness):
    from types import SimpleNamespace
    from yoke_cli.config import setup_facts_summary
    from yoke_core.hooks import session_dispatch_orientation as source
    from yoke_core.hooks import session_dispatch_cursor as cursor
    from yoke_contracts.session_model_facts import SessionModelFacts

    monkeypatch.setattr(
        setup_facts_summary,
        "orientation_lines",
        lambda _: ["Setup: unknown checkout-binding"],
    )
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "")
    if harness == "cursor":
        body = cursor._render_orientation(
            SimpleNamespace(payload={"session_id": "session"}), "/external", ""
        )
    elif harness == "codex":
        body = source._render_codex_orientation(
            "session", "/external", "", SessionModelFacts(), None
        )
    else:
        body = source._render_claude_orientation(
            "session", "/external", "", "claude-code", SessionModelFacts()
        )
    assert body.count("Setup: unknown checkout-binding") == 1
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())


def test_repeated_hook_does_not_reread_setup(monkeypatch):
    import json
    from yoke_cli.config import setup_facts_summary

    delivered = []
    reads = []
    monkeypatch.setattr(orientation, "_project_root", lambda _: Path("/external"))
    monkeypatch.setattr(orientation, "orientation_delivered", lambda _: bool(delivered))
    monkeypatch.setattr(orientation, "record_orientation_attempt", lambda _: False)
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "")

    def setup(root):
        reads.append(root)
        return ["Setup: unknown checkout-binding"]

    monkeypatch.setattr(setup_facts_summary, "orientation_lines", setup)
    payload = json.dumps({"session_id": "session", "cwd": "/external"})
    event = orientation.session_orientation_event(cursor=False)
    first = orientation.orientation_for_hook(event, payload)
    assert "Setup: unknown checkout-binding" in first
    delivered.append(True)
    assert orientation.orientation_for_hook(event, payload) is None
    assert reads == [Path("/external")]
