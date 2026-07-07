"""AC-2 / AC-7 coverage: section-style additive transforms wire body sync.

Pre-AC-2, the section paths re-rendered the local body but never told
GitHub. Every ``items.section.upsert``, ``items.section.delete``,
``items.progress_log.append``, ``items.structured_field.section_upsert``,
and ``items.structured_field.section_append`` left the GH body stale.
The fix is one shared helper :func:`yoke_core.domain.sections.sync_body_after_section_mutation`
that every section mutation path now calls; the same helper emits
``SyncFailed(operation="body")`` on transport failure so ``/yoke
resync --fix`` is the canonical convergence mechanism.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain import sections as _sections
from yoke_core.domain.handlers import items_section as _handlers
from yoke_core.domain.handlers import items_progress_log as _progress_handlers
from yoke_core.domain.handlers import (
    items_structured_field as _structured_handlers,
)
from yoke_core.domain import item_field_transform_sections as _ift_sec
from yoke_core.domain.item_field_transform import TransformResult
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    ActorContext,
    TargetRef,
)


# ---------------------------------------------------------------------------
# Shared sync helper unit coverage
# ---------------------------------------------------------------------------


class TestSyncBodyAfterSectionMutation:
    def test_returns_ok_when_sync_succeeds(self):
        with patch(
            "yoke_core.domain.backlog_rendering._sync_body",
            return_value=(True, "full"),
        ):
            ok, reason = _sections.sync_body_after_section_mutation(
                42, "upsert",
            )
        assert ok is True
        assert reason == ""

    def test_emits_sync_failed_on_transport_failure(self):
        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        with patch(
            "yoke_core.domain.backlog_rendering._sync_body",
            return_value=(False, None),
        ), patch(
            "yoke_core.domain.backlog_rendering._record_sync_failure",
            side_effect=capture,
        ):
            ok, reason = _sections.sync_body_after_section_mutation(
                43, "append",
            )
        assert ok is False
        assert "sync_body failed" in reason
        assert recorded == [(43, "body", "section append: sync_body failed")]


# ---------------------------------------------------------------------------
# Section transform paths (item_field_transform_sections) call the helper
# ---------------------------------------------------------------------------


class TestSectionTransformBodySyncWiring:
    def test_section_upsert_calls_sync_helper(self):
        calls: list[tuple] = []

        def fake_sync(item_id, operation):
            calls.append((item_id, operation))
            return True, ""

        with patch.object(
            _ift_sec, "_find_fields_with_section", return_value=[],
        ), patch.object(
            _sections, "upsert_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "get_section", return_value="rendered content\n",
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            side_effect=fake_sync,
        ):
            result = _ift_sec.section_upsert(
                item_id=50, section="Notes", content="hello world",
            )
        assert result.success is True
        assert calls == [(50, "upsert")]
        assert result.warning == ""

    def test_section_upsert_surfaces_warning_on_sync_failure(self):
        def failing_sync(item_id, operation):
            return False, "section upsert: sync_body failed"

        with patch.object(
            _ift_sec, "_find_fields_with_section", return_value=[],
        ), patch.object(
            _sections, "upsert_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "get_section", return_value="rendered content\n",
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            side_effect=failing_sync,
        ):
            result = _ift_sec.section_upsert(
                item_id=51, section="Notes", content="hello",
            )
        assert result.success is True
        assert "sync_body failed" in result.warning

    def test_section_append_calls_sync_helper(self):
        calls: list[tuple] = []

        def fake_sync(item_id, operation):
            calls.append((item_id, operation))
            return True, ""

        persisted = "## 2026-05-19T00:00:00Z entry — head\nbody-text\n"
        with patch.object(
            _sections, "upsert_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "get_section",
            side_effect=["", persisted],
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            side_effect=fake_sync,
        ):
            result = _ift_sec.section_append(
                item_id=52, section="Progress Log",
                headline="head", content="body-text",
            )
        assert result.success is True
        assert calls == [(52, "append")]


# ---------------------------------------------------------------------------
# items.section.* handlers surface github_sync_degraded warnings
# ---------------------------------------------------------------------------


def _make_section_request(*, function_id: str, item_id: int, section: str,
                         payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s", actor_id="agent"),
        target=TargetRef(kind="section", item_id=item_id, section_name=section),
        payload=payload,
    )


def _make_item_request(*, function_id: str, item_id: int,
                       payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s", actor_id="agent"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


class TestItemSectionHandlerWarningSurfacing:
    def test_handle_upsert_attaches_warning_when_sync_fails(self):
        def failing_sync(item_id, operation):
            return False, "section upsert: sync_body failed"

        with patch.object(
            _sections, "upsert_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "get_section", return_value="content\n",
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            side_effect=failing_sync,
        ):
            outcome = _handlers.handle_upsert(_make_section_request(
                function_id="items.section.upsert",
                item_id=60, section="Notes",
                payload={"content": "content"},
            ))

        assert outcome.primary_success is True
        codes = [w.code for w in outcome.warnings]
        assert "github_sync_degraded" in codes
        assert outcome.warnings[0].recovery_function == "resync.fix"

    def test_handle_upsert_attaches_no_warning_when_sync_succeeds(self):
        with patch.object(
            _sections, "upsert_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "get_section", return_value="content\n",
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            return_value=(True, ""),
        ):
            outcome = _handlers.handle_upsert(_make_section_request(
                function_id="items.section.upsert",
                item_id=61, section="Notes",
                payload={"content": "content"},
            ))

        assert outcome.primary_success is True
        assert outcome.warnings == []

    def test_handle_delete_attaches_warning_when_sync_fails(self):
        def failing_sync(item_id, operation):
            return False, "section delete: sync_body failed"

        with patch.object(
            _sections, "get_section", return_value="existing\n",
        ), patch.object(
            _sections, "delete_section", return_value=None,
        ), patch.object(
            _sections, "_rerender_body", return_value=True,
        ), patch.object(
            _sections, "_emit_section_event", return_value=None,
        ), patch.object(
            _sections, "sync_body_after_section_mutation",
            side_effect=failing_sync,
        ):
            outcome = _handlers.handle_delete(_make_section_request(
                function_id="items.section.delete",
                item_id=62, section="Notes",
                payload={},
            ))

        assert outcome.primary_success is True
        codes = [w.code for w in outcome.warnings]
        assert "github_sync_degraded" in codes


class TestAppendStyleHandlerWarningSurfacing:
    def test_structured_section_upsert_attaches_warning_when_sync_fails(self):
        result = TransformResult(
            success=True, operation="section-upsert", item_id=70,
            section="Notes", changed=True, new_line_count=1,
            verification="ok", warning="section upsert: sync_body failed",
        )
        with patch.object(
            _structured_handlers.item_field_transform,
            "section_upsert",
            return_value=result,
        ):
            outcome = _structured_handlers.handle_section_upsert(
                _make_item_request(
                    function_id="items.structured_field.section_upsert",
                    item_id=70,
                    payload={"section": "Notes", "content": "content"},
                )
            )

        assert outcome.primary_success is True
        assert [w.code for w in outcome.warnings] == ["github_sync_degraded"]

    def test_structured_section_append_attaches_warning_when_sync_fails(self):
        result = TransformResult(
            success=True, operation="section-append", item_id=71,
            section="Progress Log", changed=True, old_line_count=0,
            new_line_count=2, verification="ok",
            warning="section append: sync_body failed",
        )
        with patch.object(
            _structured_handlers.item_field_transform,
            "section_append",
            return_value=result,
        ):
            outcome = _structured_handlers.handle_section_append(
                _make_item_request(
                    function_id="items.structured_field.section_append",
                    item_id=71,
                    payload={
                        "section": "Progress Log",
                        "headline": "head",
                        "content": "content",
                    },
                )
            )

        assert outcome.primary_success is True
        assert [w.code for w in outcome.warnings] == ["github_sync_degraded"]

    def test_progress_log_append_attaches_warning_when_sync_fails(self):
        result = TransformResult(
            success=True, operation="section-append", item_id=72,
            section="Progress Log", changed=True, old_line_count=0,
            new_line_count=2, verification="ok",
            warning="section append: sync_body failed",
        )
        with patch.object(
            _progress_handlers.item_field_transform,
            "section_append",
            return_value=result,
        ):
            outcome = _progress_handlers.handle_append(
                _make_item_request(
                    function_id="items.progress_log.append",
                    item_id=72,
                    payload={"headline": "head", "content": "content"},
                )
            )

        assert outcome.primary_success is True
        assert [w.code for w in outcome.warnings] == ["github_sync_degraded"]


# ---------------------------------------------------------------------------
# No new items.section.append function id was added
# ---------------------------------------------------------------------------


class TestNoAppendFunctionAdded:
    def test_items_section_registrations_remain_upsert_delete_get(self):
        """The registered function ids on the handler module must be exactly
        the three pre-existing ones — adding a fourth ``items.section.append``
        would create a redundant surface (``items.progress_log.append`` and
        ``items.structured_field.section_append`` cover the append needs)."""
        registered = {entry["function_id"] for entry in _handlers.REGISTRATIONS}
        assert registered == {
            "items.section.upsert",
            "items.section.delete",
            "items.section.get",
        }
