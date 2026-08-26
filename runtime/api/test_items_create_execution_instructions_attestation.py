"""Non-web item filing attests the operator execution-instruction read.

``items.create`` refuses a `cli` / `harness_skill` filing that never sent
``execution_instructions_considered``, and the refusal names that
create's own retrieval command instead of a generic validation error.
The web form renders the blocks itself, promotion carries an already-filed
item forward, and previews and disposable test databases are the same
exemptions the typed entry-surface gate already applies.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.item_entry_surface import (
    ITEM_ENTRY_SURFACE_ENV,
    enforce_execution_instructions_considered,
)


_REFUSAL_CODE = "execution_instructions_not_considered"


@pytest.fixture(autouse=True)
def _live_authority(monkeypatch):
    """Run every case as a non-disposable database with no ambient surface."""
    monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.item_entry_surface.is_test_isolated_database",
        lambda: False,
    )


@pytest.fixture()
def created(monkeypatch):
    """Capture what the handler forwards when the gate lets a create run."""
    captured = {}

    def _record(**kwargs):
        captured.update(kwargs)
        return {"success": True, "item_id": 11, "item_ref": "YOK-11"}

    monkeypatch.setattr(
        "yoke_core.domain.backlog_create_op.execute_create", _record,
    )
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda conn, item_id: [],
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda *a, **k: _NullConn(),
    )
    return captured


class _NullConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _request(payload):
    return FunctionCallRequest(
        function="items.create",
        actor=ActorContext(session_id="attestation-test"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestGate:
    @pytest.mark.parametrize("surface", ["cli", "harness_skill"])
    def test_non_web_surface_without_attestation_refuses(self, surface):
        message = enforce_execution_instructions_considered(
            workflow="dash", project="yoke", entry_surface=surface,
        )
        assert message == (
            "Retrieve the operator execution instructions first: yoke "
            "workflow execution-instruction resolve --workflow dash "
            "--project yoke — then refile with "
            "--execution-instructions-considered"
        )

    def test_refusal_names_the_workflow_and_project_of_this_create(self):
        message = enforce_execution_instructions_considered(
            workflow="issue", project="external-webapp", entry_surface="cli",
        )
        assert "--workflow issue --project external-webapp" in message

    def test_unnamed_project_still_teaches_the_read(self):
        message = enforce_execution_instructions_considered(
            workflow="issue", entry_surface="cli",
        )
        assert "--project <the project you are filing in>" in message

    @pytest.mark.parametrize("surface", ["web_form", "promotion"])
    def test_exempt_surfaces_file_without_attestation(self, surface):
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke", entry_surface=surface,
        ) is None

    def test_attested_filing_passes(self):
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke", entry_surface="cli",
            considered=True,
        ) is None

    def test_dry_run_preview_is_exempt(self):
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke", entry_surface="cli",
            dry_run=True,
        ) is None

    def test_disposable_database_is_exempt(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.item_entry_surface.is_test_isolated_database",
            lambda: True,
        )
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke", entry_surface="cli",
        ) is None

    def test_ambient_surface_env_is_gated_too(self, monkeypatch):
        monkeypatch.setenv(ITEM_ENTRY_SURFACE_ENV, "harness_skill")
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke",
        ) is not None

    def test_no_resolvable_surface_defers_to_the_entry_surface_gate(self):
        # The typed entry-surface gate owns this refusal; attesting a
        # create that names no surface would only mask that message.
        assert enforce_execution_instructions_considered(
            workflow="dash", project="yoke",
        ) is None


class TestHandler:
    def test_unattested_cli_filing_refuses_with_the_teaching_message(self):
        outcome = handle_item_create(
            _request({
                "title": "T",
                "workflow": "dash",
                "project": "yoke",
                "entry_surface": "cli",
            }),
        )
        assert outcome.primary_success is False
        assert outcome.error.code == _REFUSAL_CODE
        assert (
            "yoke workflow execution-instruction resolve --workflow dash "
            "--project yoke" in outcome.error.message
        )
        assert "--execution-instructions-considered" in outcome.error.message

    def test_attested_filing_records_the_flag_on_the_receipt(self, created):
        outcome = handle_item_create(
            _request({
                "title": "T",
                "workflow": "dash",
                "project": "yoke",
                "entry_surface": "cli",
                "execution_instructions_considered": True,
            }),
        )
        assert outcome.primary_success is True
        assert created["title"] == "T"
        assert (
            outcome.result_payload["execution_instructions_considered"] is True
        )

    def test_web_form_filing_is_unaffected(self, created):
        outcome = handle_item_create(
            _request({
                "title": "Web dash",
                "workflow": "dash",
                "project": "yoke",
                "entry_surface": "web_form",
            }),
        )
        assert outcome.primary_success is True
        assert (
            outcome.result_payload["execution_instructions_considered"] is False
        )

    def test_registration_declares_the_guardrail(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup("items.create")
        assert "execution_instructions_considered" in entry.guardrails
