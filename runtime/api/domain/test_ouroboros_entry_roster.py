"""Roster shape of ouroboros.entry.list: compact rows, keyset, filters."""

from __future__ import annotations

from yoke_core.domain.handlers import ouroboros_reads
from yoke_core.domain.ouroboros_entries import cmd_insert_entry, cmd_mark_reviewed
from yoke_core.domain.ouroboros_entry_roster import (
    COMPACT_ENTRY_FIELDS,
    ROSTER_PREVIEW_LENGTH,
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
        conn,
        timestamp,
        "tester",
        "ctx",
        "observation",
        body,
        project,
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

    def test_preview_is_bounded_without_returning_full_evidence(self, test_db):
        prefix = "Evidence 🔎 " + "x" * ROSTER_PREVIEW_LENGTH
        _seed(test_db, timestamp="2026-01-01T00:00:00Z", body=prefix + "hidden-tail")
        entry = list_roster_page(test_db, project="yoke")["entries"][0]
        assert entry["preview"] == prefix[:ROSTER_PREVIEW_LENGTH] + "…"
        assert "body" not in entry
        assert "hidden-tail" not in str(entry)

    def test_short_preview_normalizes_whitespace_without_ellipsis(self, test_db):
        _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="Line one\n\nLine two")
        entry = list_roster_page(test_db, project="yoke")["entries"][0]
        assert entry["preview"] == "Line one Line two"

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
            _request(
                {
                    "project": "yoke",
                    "shape": "roster",
                    "limit": 2,
                    "cursor": cursor,
                }
            )
        )
        first_ids = {row["id"] for row in first.result_payload["entries"]}
        second_ids = {row["id"] for row in second.result_payload["entries"]}
        assert not first_ids & second_ids
        newest = list_roster_page(
            test_db,
            project="yoke",
            limit=1,
        )["entries"][0]["id"]
        assert newest not in second_ids
        assert newest not in first_ids

    def test_reviewed_filter_applies_before_the_page(self, test_db):
        older = _seed(
            test_db,
            timestamp="2026-01-01T00:00:00Z",
            body="old-open",
        )
        reviewed = _seed(
            test_db,
            timestamp="2026-01-02T00:00:00Z",
            body="reviewed",
        )
        cmd_mark_reviewed(test_db, reviewed)
        test_db.commit()
        _seed(test_db, timestamp="2026-01-03T00:00:00Z", body="new-open")
        first = ouroboros_reads.handle_ouroboros_entry_list(
            _request(
                {
                    "project": "yoke",
                    "shape": "roster",
                    "review_state": "unreviewed",
                    "limit": 1,
                }
            )
        )
        assert first.result_payload["entries"][0]["id"] != reviewed
        assert first.result_payload["matching_count"] == 2
        page = ouroboros_reads.handle_ouroboros_entry_list(
            _request(
                {
                    "project": "yoke",
                    "shape": "roster",
                    "review_state": "unreviewed",
                    "limit": 1,
                    "cursor": first.result_payload["next_cursor"],
                }
            )
        )
        assert page.result_payload["entries"][0]["id"] == older

    def test_malformed_cursor_names_reload_recovery(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request(
                {
                    "project": "yoke",
                    "shape": "roster",
                    "cursor": "not-a-cursor",
                }
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "Reload the Ouroboros page" in outcome.error.message

    def test_invalid_review_state_names_reload_recovery(self, test_db):
        outcome = ouroboros_reads.handle_ouroboros_entry_list(
            _request(
                {
                    "project": "yoke",
                    "shape": "roster",
                    "review_state": "pending",
                }
            )
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


def test_filed_timestamp_orders_before_paging_and_not_by_insert_id(test_db):
    latest = _seed(test_db, timestamp="2026-04-03T00:00:00Z", body="latest")
    oldest = _seed(test_db, timestamp="2026-04-01T00:00:00Z", body="oldest")
    middle = _seed(test_db, timestamp="2026-04-02T00:00:00Z", body="middle")
    first = list_roster_page(test_db, project="yoke", limit=1)
    assert [row["id"] for row in first["entries"]] == [latest]
    second = list_roster_page(
        test_db, project="yoke", limit=1, cursor=first["next_cursor"]
    )
    assert [row["id"] for row in second["entries"]] == [middle]
    ascending = list_roster_page(
        test_db, project="yoke", sort={"column": "timestamp", "direction": "asc"}
    )
    assert [row["id"] for row in ascending["entries"]] == [oldest, middle, latest]


def test_roster_cursor_cannot_cross_sort_or_project_boundaries(test_db):
    import pytest
    from yoke_core.domain.ouroboros_entry_roster import RosterCursorError

    _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="one")
    first = list_roster_page(test_db, project="yoke", limit=1)
    with pytest.raises(RosterCursorError):
        list_roster_page(
            test_db,
            project="yoke",
            sort={"column": "category", "direction": "asc"},
            cursor=first["next_cursor"],
        )
    with pytest.raises(RosterCursorError):
        list_roster_page(test_db, project_ids=[], cursor=first["next_cursor"])


def test_explicit_empty_project_scope_never_becomes_unscoped(test_db):
    _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="private")
    page = list_roster_page(test_db, project_ids=[])
    assert page["entries"] == []
    assert page["matching_count"] == 0


def test_multi_project_roster_never_widens_unknown_project_scope(test_db):
    from runtime.api.domain.test_ouroboros_https_permissions import _project_owner

    actor = _project_owner(test_db, "yoke")
    _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="allowed")
    request = _request({"projects": ["yoke", "unknown"], "shape": "roster"})
    request.actor.actor_id = str(actor)
    outcome = ouroboros_reads.handle_ouroboros_entry_list(request)
    assert outcome.primary_success
    assert outcome.result_payload["matching_count"] == 1
    request.payload["projects"] = ["unknown"]
    outcome = ouroboros_reads.handle_ouroboros_entry_list(request)
    assert outcome.primary_success
    assert outcome.result_payload["entries"] == []


def test_multi_project_roster_respects_explicit_actor_visibility(test_db, monkeypatch):
    from yoke_core.domain.handlers import ouroboros_roster_scope

    _seed(test_db, timestamp="2026-01-01T00:00:00Z", body="restricted")
    monkeypatch.setattr(
        ouroboros_roster_scope, "actor_visible_scope", lambda conn, request: set()
    )
    outcome = ouroboros_reads.handle_ouroboros_entry_list(
        _request({"projects": ["yoke"], "shape": "roster"})
    )
    assert outcome.primary_success
    assert outcome.result_payload["entries"] == []
