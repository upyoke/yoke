"""Semantic migration-content verifier behavior and disclosure boundary."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.migration_content_identity import (
    FUNCTION_ID,
    MigrationContentIdentityVerifyRequest,
)
from yoke_core.domain.handlers import migration_content_identity_verify as verify


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, content_sha256 TEXT)"
    )
    return conn


def _spec(name: str, digest: str) -> MigrationContentIdentityVerifyRequest:
    return MigrationContentIdentityVerifyRequest.model_validate(
        {"entries": [{"name": name, "content_sha256": digest}]}
    )


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=FUNCTION_ID,
        actor=ActorContext(actor_id="7", session_id="release-ci"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_matching_candidate_returns_only_a_semantic_verdict() -> None:
    conn = _conn()
    try:
        digest = "a" * 64
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, ?)",
            ("0015_entry", digest),
        )

        result = verify.verify_migration_content_identity(
            conn, _spec("0015_entry", digest)
        )

        assert result.status == "verified"
        assert result.verified_count == 1
        assert result.mismatched_entries == []
        assert set(result.model_dump()) == {
            "status",
            "verified_count",
            "mismatched_entries",
        }
        assert digest not in result.model_dump_json()
    finally:
        conn.close()


def test_mismatch_names_the_entry_without_disclosing_either_digest() -> None:
    conn = _conn()
    try:
        recorded = "a" * 64
        candidate = "b" * 64
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, ?)",
            ("0015_entry", recorded),
        )

        result = verify.verify_migration_content_identity(
            conn, _spec("0015_entry", candidate)
        )

        serialized = result.model_dump_json()
        assert result.status == "mismatch"
        assert result.mismatched_entries == ["0015_entry"]
        assert recorded not in serialized
        assert candidate not in serialized
    finally:
        conn.close()


def test_handler_rejects_duplicate_candidate_names_before_reading(monkeypatch) -> None:
    monkeypatch.setattr(
        verify.db_helpers,
        "connect",
        lambda: (_ for _ in ()).throw(AssertionError("database read attempted")),
    )
    payload = {
        "entries": [
            {"name": "0015_entry", "content_sha256": "a" * 64},
            {"name": "0015_entry", "content_sha256": "b" * 64},
        ]
    }

    outcome = verify.handle_migration_content_identity_verify(_request(payload))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_handler_types_an_unreadable_ledger_as_unavailable(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(verify.db_helpers, "connect", lambda: conn)
    payload = {
        "entries": [
            {"name": "0015_entry", "content_sha256": "a" * 64},
        ]
    }

    outcome = verify.handle_migration_content_identity_verify(_request(payload))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "migration_identity_verification_unavailable"
    assert "applied_migrations" not in outcome.error.message
    conn.close()
