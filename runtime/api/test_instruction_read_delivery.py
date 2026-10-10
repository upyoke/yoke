"""Dedicated section and Progress Log reads carry live operator authority."""

import io
from types import SimpleNamespace

from yoke_core.domain import db_helpers, sections
from yoke_core.domain.handlers import items_section, items_progress_log
from yoke_cli.commands.adapters.workflow_execution_instructions import (
    write_item_content,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.test_execution_instruction_delivery import seed
from runtime.api.item_page_reads_test_support import _connection
from runtime.api.test_workflow_execution_instruction_functions import (
    _UnclosableConnection,
)


def test_named_section_and_progress_log_reads_attach_stage_delivery(monkeypatch):
    conn = _UnclosableConnection(_connection())
    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    monkeypatch.setattr(sections, "get_section", lambda *_a: "Stored section content")
    rule = seed(
        conn,
        "Review rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["reviewing"],
    )
    for handler, function, target in (
        (
            items_section.handle_get,
            "items.section.get",
            TargetRef(kind="section", item_id=51, section_name="Notes"),
        ),
        (
            items_progress_log.handle_get,
            "items.progress_log.get",
            TargetRef(kind="item", item_id=51),
        ),
    ):
        request = FunctionCallRequest(
            function=function,
            actor=ActorContext(session_id="test"),
            target=target,
            payload={},
        )
        outcome = handler(request)
        assert outcome.primary_success
        assert [
            row["id"] for row in outcome.result_payload["execution_instructions"]
        ] == [rule]
        assert outcome.result_payload["content"] == "Stored section content"


def test_section_renderer_describes_instructions_before_requested_content():
    stdout = io.StringIO()
    write_item_content(
        SimpleNamespace(
            success=True,
            result={
                "public_ref": "EX-1",
                "content": "Section text",
                "execution_instructions": [{"content": "Read rule"}],
            },
        ),
        stdout,
        io.StringIO(),
    )
    rendered = stdout.getvalue()
    assert "Read rule" not in rendered
    assert rendered.index("yoke items get EX-1 --json") < rendered.index("Section text")
    assert rendered.endswith("Section text\n")
