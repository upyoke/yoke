"""Claude's served context window, from the one surface that states it.

The status line is the only Claude artifact carrying
``context_window.context_window_size``, so these cover the whole path it
travels: read it out of the payload, record it under the session, fold it
into the session's served facts beside the transcript's model, and keep the
relay asking until it has arrived. The last one is the regression that
matters most — the window is written by a different process than the model
and normally lands after it, so a settle rule keyed on the model alone
drops it permanently and silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.session_context_window_sources import (
    SERVED_CONTEXT_WINDOW_SOURCES,
    attests_context_window,
    served_facts_settled,
)
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_harness import claude_status_line
from yoke_harness.model_attestation import attest_served_facts


SESSION = "8b1d0a5c-4f2e-4a77-9c31-6d0f2b7e5a44"


@pytest.fixture()
def yoke_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the recording directory at a scratch home for one test."""
    from yoke_cli.config import machine_config

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(machine_config, "yoke_home", lambda: home)
    return home


def _payload(window: int | None, *, session_id: str = SESSION) -> dict:
    payload: dict = {
        "session_id": session_id,
        "model": {"id": "claude-opus-5", "display_name": "Opus"},
    }
    if window is not None:
        payload["context_window"] = {
            "context_window_size": window,
            "used_percentage": 8,
        }
    return payload


def _transcript(path: Path, model: str = "claude-opus-5") -> Path:
    path.write_text(
        json.dumps(
            {"type": "assistant", "effort": "high", "message": {"model": model}}
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_the_extended_tier_is_recorded_from_the_payload(yoke_home: Path) -> None:
    assert claude_status_line.record_context_window(_payload(1_000_000)) == 1_000_000

    assert claude_status_line.recorded_context_window(SESSION) == 1_000_000


def test_the_standard_window_is_recorded_just_as_plainly(yoke_home: Path) -> None:
    """200k is an attestation too — only absence means "not attested"."""
    claude_status_line.record_context_window(_payload(200_000))

    assert claude_status_line.recorded_context_window(SESSION) == 200_000


def test_a_payload_stating_no_window_records_nothing(yoke_home: Path) -> None:
    assert claude_status_line.record_context_window(_payload(None)) is None

    assert claude_status_line.recorded_context_window(SESSION) is None


def test_a_session_id_that_could_escape_the_directory_is_refused(
    yoke_home: Path,
) -> None:
    payload = _payload(1_000_000, session_id="../../etc/passwd")

    claude_status_line.record_context_window(payload)

    assert claude_status_line.record_path("../../etc/passwd") is None
    assert not list(yoke_home.rglob("passwd"))


def test_the_recorded_window_joins_the_transcript_model(
    tmp_path: Path, yoke_home: Path
) -> None:
    """The two artifacts fold into one reading of the session."""
    claude_status_line.record_context_window(_payload(1_000_000))
    transcript = _transcript(tmp_path / "session.jsonl")

    facts = attest_served_facts(
        "claude-code",
        {"session_id": SESSION},
        transcript_path=str(transcript),
    )

    assert facts.model == "claude-opus-5"
    assert facts.reasoning_effort == "high"
    assert facts.context_window_tokens == 1_000_000


def test_a_session_whose_status_line_has_not_run_reports_no_window(
    tmp_path: Path, yoke_home: Path
) -> None:
    """Absence of proof is not proof of the standard window."""
    transcript = _transcript(tmp_path / "session.jsonl")

    facts = attest_served_facts(
        "claude-code",
        {"session_id": SESSION},
        transcript_path=str(transcript),
    )

    assert facts.model == "claude-opus-5"
    assert facts.context_window_tokens is None


def test_the_window_is_reported_before_the_transcript_names_a_model(
    tmp_path: Path, yoke_home: Path
) -> None:
    """The status line runs first; its answer does not wait for the other."""
    claude_status_line.record_context_window(_payload(1_000_000))

    facts = attest_served_facts(
        "claude-code",
        {"session_id": SESSION},
        transcript_path=str(tmp_path / "absent.jsonl"),
    )

    assert facts.model is None
    assert facts.context_window_tokens == 1_000_000


def test_a_claude_session_is_not_settled_until_its_window_arrives() -> None:
    """The regression: settling on the model alone strands the window.

    The relay stops reading a session's artifacts once its facts are
    settled, and Claude's window lands after its model, so a rule that
    settled on the model would mark the session done one event before the
    window was ever readable.
    """
    model_only = SessionModelFacts(model="claude-opus-5")

    assert not served_facts_settled(model_only, harness_id="claude-code")
    assert served_facts_settled(
        SessionModelFacts(model="claude-opus-5", context_window_tokens=1_000_000),
        harness_id="claude-code",
    )


def test_a_cursor_session_settles_on_its_model_alone() -> None:
    """Cursor states no window, so waiting for one would never settle."""
    assert served_facts_settled(
        SessionModelFacts(model="cursor-grok-4.6-xhigh"), harness_id="cursor"
    )


def test_nothing_settles_before_a_model_is_attested() -> None:
    assert not served_facts_settled(SessionModelFacts(), harness_id="codex")
    assert not served_facts_settled(
        SessionModelFacts(context_window_tokens=400_000), harness_id="codex"
    )


def test_the_window_sources_declare_one_deferral_and_two_surfaces() -> None:
    assert attests_context_window("claude-code")
    assert attests_context_window("codex")
    assert not attests_context_window("cursor")
    assert SERVED_CONTEXT_WINDOW_SOURCES["cursor"] == ""


def test_the_status_line_names_the_model_window_and_usage() -> None:
    assert claude_status_line.status_line(_payload(1_000_000)) == "Opus · 1M · 8% used"


def test_the_status_line_omits_usage_the_payload_has_not_stated() -> None:
    """Usage is null before the first API call and after a compact."""
    payload = _payload(200_000)
    payload["context_window"]["used_percentage"] = None

    assert claude_status_line.status_line(payload) == "Opus · 200K"


def test_the_status_line_survives_a_payload_it_cannot_read() -> None:
    """A display surface reports nothing rather than raising into the UI."""
    assert claude_status_line.status_line({}) == ""
