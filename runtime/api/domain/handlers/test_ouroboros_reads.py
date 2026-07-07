"""Handler coverage for ouroboros.entry.list / ouroboros.entry.get."""

from __future__ import annotations

from yoke_core.domain.handlers import ouroboros_reads
from yoke_core.domain.ouroboros_entries import cmd_insert_entry, cmd_mark_reviewed
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _seed_entry(conn, *, timestamp: str, body: str, project=None) -> int:
    entry_id = cmd_insert_entry(
        conn, timestamp, "tester", "ctx", "observation", body, project,
    )
    conn.commit()
    return int(entry_id)


class TestOuroborosEntryList:
    def test_lists_typed_rows(self, test_db):
        _seed_entry(test_db, timestamp="2026-01-01T00:00:00Z", body="first")
        _seed_entry(test_db, timestamp="2026-01-02T00:00:00Z", body="second")
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request("ouroboros.entry.list")
        )
        assert outcome.primary_success
        entries = outcome.result_payload["entries"]
        assert [e["body"] for e in entries] == ["first", "second"]
        assert all(isinstance(e["id"], int) for e in entries)
        assert entries[0]["agent"] == "tester"
        assert entries[0]["category"] == "observation"

    def test_unreviewed_filter(self, test_db):
        reviewed_id = _seed_entry(
            test_db, timestamp="2026-01-01T00:00:00Z", body="reviewed",
        )
        cmd_mark_reviewed(test_db, reviewed_id)
        test_db.commit()
        _seed_entry(test_db, timestamp="2026-01-02T00:00:00Z", body="open")
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request("ouroboros.entry.list", {"unreviewed": True})
        )
        assert outcome.primary_success
        assert [e["body"] for e in outcome.result_payload["entries"]] == ["open"]

    def test_unknown_project_is_payload_invalid(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request("ouroboros.entry.list", {"project": "definitely-missing"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestOuroborosEntryGet:
    def test_returns_full_entry(self, test_db):
        entry_id = _seed_entry(
            test_db, timestamp="2026-01-01T00:00:00Z",
            body="line one\nline two",
        )
        outcome = ouroboros_reads.handle_ouroboros_entry_get(
            _request("ouroboros.entry.get", {"entry_id": entry_id})
        )
        assert outcome.primary_success
        entry = outcome.result_payload["entry"]
        assert entry["id"] == entry_id
        # The per-entry reader preserves newlines (the list CLI collapses
        # them only at pipe-row render time).
        assert entry["body"] == "line one\nline two"
        assert "archived_at" in entry

    def test_not_found(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_get(
            _request("ouroboros.entry.get", {"entry_id": 999999})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_rejects_non_integer_id(self):
        outcome = ouroboros_reads.handle_ouroboros_entry_get(
            _request("ouroboros.entry.get", {"entry_id": "abc"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
