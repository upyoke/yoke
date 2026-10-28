"""Native permission evidence must belong to this session and its newest turn."""

import json

import pytest

from yoke_harness.codex_session_posture import read_codex_session_posture

SESSION = "11111111-1111-4111-8111-111111111111"
PERMISSIONS = {
    "approval_policy": "never",
    "sandbox_policy": {"type": "danger-full-access"},
}


def transcript(tmp_path, monkeypatch, *turns, identity=SESSION):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    root = tmp_path / "sessions"
    root.mkdir(exist_ok=True)
    target = root / f"rollout-{SESSION}.jsonl"
    rows = [{"type": "session_meta", "payload": {"id": identity}}]
    rows.extend({"type": "turn_context", "payload": turn} for turn in turns)
    target.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return target


def test_reads_only_permission_fields(tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, {**PERMISSIONS, "private": "not returned"})
    facts, reason = read_codex_session_posture(SESSION)
    assert not reason
    assert facts == {
        "approval_policy": "never",
        "approvals_reviewer": None,
        "sandbox_mode": "danger-full-access",
    }


def test_latest_turn_wins_over_permissive_history(tmp_path, monkeypatch):
    transcript(
        tmp_path,
        monkeypatch,
        PERMISSIONS,
        {
            "approval_policy": "on-request",
            "approvals_reviewer": "auto_review",
            "sandbox_policy": {"type": "workspace-write"},
        },
    )
    facts, _ = read_codex_session_posture(SESSION)
    assert facts["approval_policy"] == "on-request"
    assert facts["approvals_reviewer"] == "auto_review"
    assert facts["sandbox_mode"] == "workspace-write"


def test_missing_newest_fields_never_borrows_older_values(tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, PERMISSIONS, {})
    facts, _ = read_codex_session_posture(SESSION)
    assert set(facts.values()) == {None}


@pytest.mark.parametrize("tail", ['{"type":"turn_context",', "[]\n", '"invalid"\n'])
def test_unreadable_newer_evidence_fails_closed(tmp_path, monkeypatch, tail):
    target = transcript(tmp_path, monkeypatch, PERMISSIONS)
    with target.open("a") as handle:
        handle.write(tail)
    facts, reason = read_codex_session_posture(SESSION)
    assert facts is None


def test_mismatched_native_identity_cannot_pass(tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, PERMISSIONS, identity="other-session")
    facts, reason = read_codex_session_posture(SESSION)
    assert facts is None


def test_missing_transcript_does_not_read_cli_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        'approval_policy="never"\nsandbox_mode="danger-full-access"\n'
    )
    facts, reason = read_codex_session_posture(SESSION)
    assert facts is None


def test_permission_statement_outside_tail_cannot_pass(tmp_path, monkeypatch):
    target = transcript(tmp_path, monkeypatch, PERMISSIONS)
    with target.open("a") as handle:
        handle.write(json.dumps({"type": "response_item", "text": "x" * (2 << 20)}))
    facts, reason = read_codex_session_posture(SESSION)
    assert facts is None


def test_invalid_identity_is_not_a_glob(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    facts, reason = read_codex_session_posture("*")
    assert facts is None


def test_archived_transcripts_are_supported(tmp_path, monkeypatch):
    target = transcript(tmp_path, monkeypatch, PERMISSIONS)
    archive = tmp_path / "archived_sessions"
    archive.mkdir()
    target.rename(archive / target.name)
    facts, reason = read_codex_session_posture(SESSION)
    assert facts["approval_policy"] == "never"
    assert not reason
