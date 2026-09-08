"""Roster shape of ouroboros.entry.list: compact rows, keyset, filters."""

from __future__ import annotations

from yoke_core.domain.handlers import ouroboros_reads
from yoke_core.domain.ouroboros_entries import cmd_insert_entry, cmd_mark_reviewed
from yoke_core.domain.ouroboros_entry_roster import (
    COMPACT_ENTRY_FIELDS,
    list_roster_page,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="ouroboros.entry.list",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _seed(conn, *, timestamp: str, body: str, project="yoke") -> int:
    entry_id = cmd_insert_entry(
        conn, timestamp, "tester", "ctx", "observation", body, project,
    )
    conn.commit()
    return int(entry_id)


class TestOuroborosEntryRosterList:
    def test_compact_rows_omit_body_and_return_matching_count(self, test_db):
        _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="secret")
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request({"project": "yoke", "shape": "roster"})
        )
        assert outcome.primary_success
        entry = outcome.result_payload["entries"][0]
        assert "body" not in entry
        assert "archived_at" not in entry
        assert "instruction" not in (entry.get("promoted_dash") or {})
        for name in COMPACT_ENTRY_FIELDS:
            assert name in entry
        assert outcome.result_payload["matching_count"] == 1
        assert outcome.result_payload["next_cursor"] is None

    def test_legacy_list_still_returns_body(self, test_db):
        _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="secret")
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request({"project": "yoke"})
        )
        assert outcome.result_payload["entries"][0]["body"] == "secret"

    def test_keyset_skips_newer_inserts_on_load_more(self, test_db):
        for index, body in enumerate(("a", "b", "c")):
            _seed(
                test_db,
                timestamp=f"2026-01-0{index + 1}T00:00:00Z",
                body=body,
            )
        first = ouroboros_reads.handle_ouroboros_entry_list(
            _request({"project": "yoke", "shape": "roster", "limit": 2})
        )
        cursor = first.result_payload["next_cursor"]
        _seed(test_db, timestamp="2026-01-09T00:00:00Z", body="newer")
        second = ouroboros_reads.handle_ouroboros_entry_list(
            _request({
                "project": "yoke", "shape": "roster", "limit": 2,
                "cursor": cursor,
            })
        )
        first_ids = {row["id"] for row in first.result_payload["entries"]}
        second_ids = {row["id"] for row in second.result_payload["entries"]}
        assert not first_ids & second_ids
        newest = list_roster_page(
            test_db, project="yoke", limit=1,
        )["entries"][0]["id"]
        assert newest not in second_ids
        assert newest not in first_ids

    def test_reviewed_filter_applies_before_the_page(self, test_db):
        older = _seed(
            test_db, timestamp="2026-01-01T00:00:00Z", body="old-open",
        )
        reviewed = _seed(
            test_db, timestamp="2026-01-02T00:00:00Z", body="reviewed",
        )
        cmd_mark_reviewed(test_db, reviewed)
        test_db.commit()
        _seed(test_db, timestamp="2026-01-03T00:00:00Z", body="new-open")
        first = ouroboros_reads.handle_ouroboros_entry_list(
            _request({
                "project": "yoke", "shape": "roster",
                "review_state": "unreviewed", "limit": 1,
            })
        )
        assert first.result_payload["entries"][0]["id"] != reviewed
        assert first.result_payload["matching_count"] == 2
        page = ouroboros_reads.handle_ouroboros_entry_list(
            _request({
                "project": "yoke", "shape": "roster",
                "review_state": "unreviewed", "limit": 1,
                "cursor": first.result_payload["next_cursor"],
            })
        )
        assert page.result_payload["entries"][0]["id"] == older

    def test_malformed_cursor_names_reload_recovery(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request({
                "project": "yoke", "shape": "roster", "cursor": "not-a-cursor",
            })
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "Reload the Ouroboros page" in outcome.error.message

    def test_invalid_review_state_names_reload_recovery(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request({
                "project": "yoke", "shape": "roster", "review_state": "pending",
            })
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "Reload the Ouroboros page" in outcome.error.message

    def test_roster_refuses_unknown_and_omitted_project(self, test_db):
        unknown = ouroboros_reads.handle_ouroboros_entry_list(
            _request({"project": "definitely-missing", "shape": "roster"})
        )
        omitted = ouroboros_reads.handle_ouroboros_entry_list(
            _request({"shape": "roster"})
        )
        assert unknown.error.code == "payload_invalid"
        assert omitted.error.code == "payload_invalid"
