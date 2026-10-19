"""Codex records the effort each turn actually ran at, and follows changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.session_model_facts import NOT_REPORTED_EFFORT
from yoke_harness.hooks import identity_codex_runtime
from yoke_harness.hooks.identity_model_facts import (
    client_model_facts,
    record_model_facts_shipped,
)
from yoke_harness.model_attestation import attest_served_facts
from runtime.harness.session_usage_test_support import machine_home  # noqa: F401

THREAD = "01a05895-484b-7ab2-b3b2-5b88a84df583"
PAYLOAD = {"session_id": THREAD, "thread_id": THREAD, "model": "gpt-6-astra"}


def _turn(effort: str | None = None, model: str = "gpt-6-astra") -> dict:
    payload: dict = {"model": model}
    if effort is not None:
        payload["effort"] = effort
    return {"type": "turn_context", "payload": payload}


def _append(path: Path, *rows: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


@pytest.fixture
def rollout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / f"rollout-2026-10-19T12-00-00-{THREAD}.jsonl"
    path.touch()
    monkeypatch.setattr(
        identity_codex_runtime, "codex_transcript_candidates", lambda _id: [path]
    )
    return path


def test_the_rollouts_stated_effort_is_recorded(rollout: Path) -> None:
    _append(rollout, _turn("xhigh"))

    assert attest_served_facts("codex", PAYLOAD).reasoning_effort == "xhigh"


def test_a_mid_session_effort_change_replaces_the_earlier_one(rollout: Path) -> None:
    _append(rollout, _turn("xhigh"))
    assert attest_served_facts("codex", PAYLOAD).reasoning_effort == "xhigh"

    _append(rollout, _turn("low"))

    assert attest_served_facts("codex", PAYLOAD).reasoning_effort == "low"


def test_a_turn_that_names_no_effort_records_not_reported(rollout: Path) -> None:
    _append(rollout, _turn("high"), _turn(None))

    facts = attest_served_facts("codex", PAYLOAD)

    assert facts.model == "gpt-6-astra"
    assert facts.reasoning_effort == NOT_REPORTED_EFFORT


def test_the_codex_config_file_never_supplies_the_effort(
    rollout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text(
        'model_reasoning_effort = "high"\n', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    _append(rollout, _turn(None))

    facts = client_model_facts("UserPromptSubmit", PAYLOAD, "codex")

    assert facts["reasoning_effort"] == NOT_REPORTED_EFFORT
    assert "requested_reasoning_effort" not in facts


def test_a_shipped_codex_session_keeps_reporting_each_turns_effort(
    rollout: Path,
) -> None:
    """The hook payload names the model, so shipping it must not settle Codex."""
    _append(rollout, _turn(None))
    assert client_model_facts("SessionStart", PAYLOAD, "codex")["reasoning_effort"] == (
        NOT_REPORTED_EFFORT
    )
    record_model_facts_shipped(PAYLOAD, "gpt-6-astra")

    _append(rollout, _turn("medium"))

    assert client_model_facts("PreToolUse", PAYLOAD, "codex")["reasoning_effort"] == (
        "medium"
    )


def test_a_shipped_claude_session_stops_reading_its_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude re-reads on user prompts only; tool-call hooks stay cheap."""
    payload = {"session_id": "claude-1", "transcript_path": "missing.jsonl"}
    record_model_facts_shipped(payload, "claude-opus-5-5")
    calls: list[str] = []
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_model_facts.resolve_model_facts",
        lambda *_args: calls.append("read"),
    )

    client_model_facts("PreToolUse", payload, "claude-code")

    assert calls == []
