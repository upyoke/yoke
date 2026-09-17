"""Handler composition and source-provenance item read tests."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import item_detail_read, item_overview_read
from yoke_core.domain.handlers import item_page_reads, items_listing
from runtime.api.item_page_reads_test_support import _connection


def test_overview_composes_through_actor_scoped_listing(monkeypatch):
    request = FunctionCallRequest(
        function="items.overview.list",
        actor=ActorContext(actor_id="71", session_id="session-visible"),
        target=TargetRef(kind="global"),
        payload={},
    )
    observed = {}

    def actor_scoped_list(inner_request):
        observed["request"] = inner_request
        return HandlerOutcome(
            result_payload={
                "rows": [
                    {
                        "id": "51",
                        "title": "Visible item",
                        "workflow_id": "dash",
                        "workflow_version_id": "11",
                        "status": "reviewing-implementation",
                        "project": "acme",
                    }
                ],
                "count": 1,
            },
            primary_success=True,
        )

    monkeypatch.setattr(items_listing, "handle_items_list", actor_scoped_list)
    monkeypatch.setattr(
        item_overview_read,
        "enrich_item_overview_rows",
        lambda rows: [
            dict(
                rows[0],
                public_ref="ACM-22",
                worktrees=[
                    {
                        "branch": "codex/footer",
                        "lane_role": "implementation",
                    }
                ],
            )
        ],
    )

    outcome = item_page_reads.handle_items_overview_list(request)

    delegated = observed["request"]
    assert delegated.function == "items.list.run"
    assert delegated.actor == request.actor
    assert "relevance" not in delegated.payload
    assert "project" not in delegated.payload
    assert {
        "priority",
        "frozen",
        "blocked",
        "blocked_reason",
        "deployed_to",
        "merged_at",
        "created_at",
        "updated_at",
        "project_id",
        "project_sequence",
    } <= set(delegated.payload["fields"])
    assert outcome.result_payload["rows"][0]["public_ref"] == "ACM-22"
    assert outcome.result_payload["rows"][0]["worktrees"][0]["branch"] == "codex/footer"

    item_page_reads.handle_items_overview_list(
        request.model_copy(update={"payload": {"relevance": "overview"}})
    )
    assert observed["request"].payload["relevance"] == "overview"


def test_overview_list_rejects_unknown_relevance():
    outcome = item_page_reads.handle_items_overview_list(
        FunctionCallRequest(
            function="items.overview.list",
            actor=ActorContext(actor_id="71", session_id="session-visible"),
            target=TargetRef(kind="global"),
            payload={"relevance": "items"},
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.relevance"


def test_dash_detail_links_back_to_its_source_field_note(monkeypatch):
    conn = _connection()
    conn.execute(
        """
        INSERT INTO ouroboros_entries VALUES (
          22890, '2026-07-25T08:00:00Z', 'codex', 'curate',
          'field-note-observation', 'The footer needs focused follow-up.',
          '2026-07-25T09:00:00Z', 7
        )
        """
    )
    conn.execute(
        """
        INSERT INTO ouroboros_entry_dispositions VALUES (
          22890, 'promote_to_dash', 'completed', 51,
          'Fix the footer', 'The footer needs focused follow-up.',
          '2026-07-25T09:00:00Z'
        )
        """
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert item["source_field_note"] == {
        "entry_id": 22890,
        "timestamp": "2026-07-25T08:00:00Z",
        "agent": "codex",
        "context": "curate",
        "category": "field-note-observation",
        "body": "The footer needs focused follow-up.",
        "reviewed_at": "2026-07-25T09:00:00Z",
        "promoted_at": "2026-07-25T09:00:00Z",
        "project_id": 7,
        "project": "acme",
    }


def _detail_request(payload):
    return FunctionCallRequest(
        function="items.detail.get",
        actor=ActorContext(actor_id="71", session_id="session-visible"),
        target=TargetRef(kind="item", item_id=51),
        payload=payload,
    )


class _SpentConnection:
    """A connection handle for the instruction read, which resolves no rows.

    The detail read closes the fixture connection before the handler opens a
    second one for execution instructions, so the second open cannot be the
    same handle.
    """

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        return None


def _instructions(monkeypatch, conn, rows):
    """Serve the fixture connection once, then a fresh handle, as live does."""
    handles = iter([conn])

    import yoke_core.domain.workflow_execution_instructions as instruction_reads

    monkeypatch.setattr(
        instruction_reads, "resolve_for_item", lambda *_args: rows
    )
    monkeypatch.setattr(
        item_detail_read.db_helpers,
        "connect",
        lambda: next(handles, _SpentConnection()),
    )


def test_detail_withholds_instruction_prose_but_never_their_existence(
    monkeypatch,
):
    conn = _connection()
    rows = [{"id": 2, "content": "Cover the full scope."}]
    _instructions(monkeypatch, conn, rows)

    outcome = item_page_reads.handle_item_detail_get(_detail_request({}))

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["execution_instructions"] == []
    assert result["include"] == []
    index = result["item"]["content_index"]["execution_instructions"]
    assert index["count"] == 1
    assert index["bytes"] == len("Cover the full scope.")
    assert index["read"] == (
        "yoke workflow execution-instruction resolve "
        "--workflow dash --project acme"
    )


def test_detail_serves_instruction_prose_with_the_content_it_governs(
    monkeypatch,
):
    conn = _connection()
    rows = [{"id": 2, "content": "Cover the full scope."}]
    _instructions(monkeypatch, conn, rows)

    outcome = item_page_reads.handle_item_detail_get(
        _detail_request({"include": ["narrative"]})
    )

    assert outcome.result_payload["execution_instructions"] == rows
    assert outcome.result_payload["include"] == ["narrative"]


def test_detail_refuses_an_unknown_section_by_name(monkeypatch):
    conn = _connection()
    _instructions(monkeypatch, conn, [])

    outcome = item_page_reads.handle_item_detail_get(
        _detail_request({"include": ["prose"]})
    )

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "prose" in outcome.error.message
    assert "narrative, body, progress_log" in outcome.error.message
    assert outcome.error.jsonpath == "$.payload.include"
