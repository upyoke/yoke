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
            orientation.SETUP_LINES_KEY: [
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
    from yoke_cli.config import project_onboarding_handoff as handoff
    from yoke_core.hooks import session_dispatch_orientation as source
    from yoke_core.hooks import session_dispatch_cursor as cursor
    from yoke_contracts.session_model_facts import SessionModelFacts

    family = "claude-code" if harness == "claude" else harness
    monkeypatch.setattr(handoff, "nearest_harness_family", lambda: family)
    monkeypatch.setattr(
        setup_facts_summary,
        "orientation_lines",
        lambda _: setup_facts_summary.summary_lines(
            {
                "rows": [{"row_id": "setup-checklist-handoff", "status": "blocked"}],
                "next_action": {
                    "command": "/yoke onboard",
                    "reason": "setup_required",
                    "home": ".yoke/docs/start/terminal-onboarding.md",
                },
            },
            orientation=True,
        ),
    )
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "")
    if harness == "cursor":
        body = cursor._render_orientation(
            SimpleNamespace(payload={"session_id": "session"}), "/external", ""
        )
    elif harness == "codex":
        body = orientation.render_scoped_orientation(
            {"session_id": "session"}, Path("/external")
        )
    else:
        body = source._render_claude_orientation(
            "session", "/external", "", "claude-code", SessionModelFacts()
        )
    assert body.count("Setup:") == body.count("Next:") == 1
    assert "blocked setup-checklist-handoff" in body
    router = "$yoke" if harness == "codex" else "/yoke"
    assert f"Next: {router} onboard (setup_required)" in body
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


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("in_project", [False, True])
def test_hook_scope_distinguishes_machine_state_from_project(
    monkeypatch, tmp_path, harness, in_project
):
    from types import SimpleNamespace
    from yoke_cli.config import setup_facts_summary
    from yoke_contracts.session_model_facts import SessionModelFacts
    from yoke_core.hooks import session_dispatch_orientation as source
    from yoke_core.hooks import session_dispatch_cursor as cursor

    home = tmp_path / "home"
    machine_state = home / ".yoke"
    machine_state.mkdir(parents=True)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_state))
    root = home / "project"
    if in_project:
        (root / ".yoke").mkdir(parents=True)
    cwd = root / "nested" if in_project else home / "outside" / "nested"
    cwd.mkdir(parents=True)
    reads = []

    def setup(selected):
        reads.append(selected)
        scope = "machine" if selected is None else "project"
        return [f"Setup: {scope} facts", "Next: yoke setup --agent"]

    monkeypatch.setattr(setup_facts_summary, "orientation_lines", setup)
    monkeypatch.setattr(global_orientation, "_project_folders", lambda: [])
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "")
    if harness == "cursor":
        body = cursor._render_orientation(
            SimpleNamespace(payload={"session_id": "session"}), str(cwd), ""
        )
    elif harness == "codex":
        body = orientation.render_scoped_orientation(
            {"session_id": "session"}, cwd
        )
    else:
        body = source._render_claude_orientation(
            "session", str(cwd), "", "claude-code", SessionModelFacts()
        )
    assert reads == [root if in_project else None]
    assert body.count("Setup:") == body.count("Next:") == 1
    assert ("outside every Yoke project" in body) is not in_project
    if not in_project:
        assert ".yoke/docs" not in body
        assert "setup_project_unbound" not in body
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())


def test_global_scope_keeps_required_hook_recovery(monkeypatch, tmp_path):
    from yoke_cli.config import setup_facts_summary

    monkeypatch.setattr(orientation, "_project_root", lambda _: None)
    monkeypatch.setattr(global_orientation, "_project_folders", lambda: [])
    monkeypatch.setattr(setup_facts_summary, "orientation_lines", lambda _: [])
    body = orientation.render_scoped_orientation(
        {
            "session_id": "session",
            orientation.REQUIRED_LINES_KEY: ["Required recovery"],
        },
        tmp_path,
    )
    assert "Required recovery" in body
    assert "outside every Yoke project" in body
    assert len(body.encode()) <= min(INLINE_CONTEXT_BYTES.values())
