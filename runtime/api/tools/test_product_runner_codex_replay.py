"""Codex product-smoke replay: start does not register, the first saved prompt does."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def receipt(outcome):
    envelope = {
        "hook_event_name": "PreToolUse",
        "context": {"decision_outcome": outcome, "chain_length": 1, "timed_out": False},
    }
    return {"event_id": "receipt", "envelope": json.dumps(envelope)}


class CodexReplay:
    """Stand-in runner: registers like the product, from the first saved prompt."""

    def __init__(self, tmp_path, *, register_at_start=False):
        self.env = {"HOME": str(tmp_path / "home")}
        self.register_at_start, self.registered, self.steps = register_at_start, set(), []

    def run(self, name, argv, *, cwd, stdin, shell, accepted=(0,)):
        self.steps.append(name)
        payload = json.loads(stdin)
        session = payload["session_id"]
        sessions = Path(self.env["HOME"]) / ".codex/sessions"
        if (name == "codex-session-start" and self.register_at_start) or (
            name == "codex-first-prompt" and list(sessions.rglob(f"*{session}.jsonl"))
        ):
            self.registered.add(session)
        self.outcome = "deny" if name == "codex-deny" else "allow"
        decision = {"hookSpecificOutput": {"permissionDecision": self.outcome}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(decision), stderr="")

    def document(self, name, argv, *, cwd):
        self.steps.append(name)
        if argv[1] != "sessions":
            return {"rows": [receipt(self.outcome)]}
        registered = argv[argv.index("--session") + 1] in self.registered
        return {"rows": [{"executor": "codex", "workspace": str(cwd)}] * registered}


def replay_codex(tmp_path, monkeypatch, commands):
    from runtime.api.tools import product_runner_hooks as hooks

    root = Path(__file__).resolve().parents[3]
    project = tmp_path / "project"
    (project / ".codex").mkdir(parents=True)
    rendered = (root / "runtime/harness/codex/hooks.json").read_text()
    (project / ".codex/hooks.json").write_text(rendered)
    monkeypatch.setattr(hooks, "HARNESS_CONFIGS", {"codex": hooks.HARNESS_CONFIGS["codex"]})
    return hooks.replay_hooks(root, project, commands, "yoke"), project


def test_codex_replay_registers_on_first_prompt_not_at_start(tmp_path, monkeypatch):
    commands = CodexReplay(tmp_path)
    proofs, project = replay_codex(tmp_path, monkeypatch, commands)
    assert commands.steps[:4] == [
        "codex-session-start",
        "codex-start-unregistered",
        "codex-first-prompt",
        "codex-registration",
    ]
    assert [d["outcome"] for d in proofs[0]["decisions"]] == ["allow", "deny"]
    saved = list((tmp_path / "home/.codex/sessions").rglob("*.jsonl"))
    assert [p.name.endswith(f"-{proofs[0]['session_id']}.jsonl") for p in saved] == [True]
    assert not list(project.rglob("*.jsonl"))


@pytest.mark.parametrize(
    ("register_at_start", "save_transcript", "refusal"),
    [(True, True, "session_registered_at_start"), (False, False, "session_registration_missing")],
)
def test_codex_replay_refuses_start_registration_and_unregistered_prompt(
    tmp_path, monkeypatch, register_at_start, save_transcript, refusal
):
    from runtime.api.tools import product_runner_hooks as hooks

    if not save_transcript:
        monkeypatch.setattr(hooks, "write_codex_transcript", lambda *args: None)
    with pytest.raises(ValueError, match=refusal):
        replay_codex(tmp_path, monkeypatch, CodexReplay(tmp_path, register_at_start=register_at_start))
