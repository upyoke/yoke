"""Tests for the domain registrar wiring (``__init_register__``).

The wiring contract: importing ``_register_scratch`` in the domain
import block AND listing it in ``_DOMAIN_REGISTRARS`` must both happen
for ``register_all_handlers()`` to actually register the new function
ids. Half-applied edits are a recurring failure mode the spec
explicitly warns against. (The historical ``_PER_TASK_REGISTRARS``
ordinal name was retired in favour of the domain-keyed tuple — see
``docs/archive/decisions/handler-registrar-naming-convention.md``.)
"""

from __future__ import annotations

import threading

import pytest
from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_register_all_handlers_includes_scratch_dispatch_inputs() -> None:
    init_register.register_all_handlers()

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "scratch.dispatch_inputs" in ids
    assert "hook.evaluate.run" in ids


def test_hook_evaluate_entry_target_kinds_and_claim_required_kind() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("hook.evaluate.run")
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.claim_required_kind is None
    assert entry.owner_module == "yoke_core.domain.handlers.hooks"
    assert entry.adapter_status == "live"
    assert entry.stability == "stable"
    assert entry.side_effects == ("hook_evaluate",)
    assert entry.emitted_event_names == ("YokeFunctionCalled",)
    assert entry.ambient_session_required is False


def test_terminal_strategy_and_field_note_commands_skip_session_gate() -> None:
    from yoke_core.domain.yoke_function_actor_identity import (
        bind_actor_identity,
    )
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    init_register.register_all_handlers()

    for function_id in (
        "strategy.doc.create",
        "strategy.ingest.run",
        "strategy.seed_defaults.run",
        "ouroboros.field_note.append",
    ):
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None
        assert entry.ambient_session_required is False
        result = bind_actor_identity(
            entry,
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(session_id=""),
                target=TargetRef(kind="global"),
                payload={},
            ),
            ambient_session_id="",
        )
        assert result.error is None
        assert result.bound_request is not None
        assert result.bound_request.actor.session_id == ""

    replace = yoke_function_registry.lookup("strategy.doc.replace")
    assert replace is not None
    assert replace.ambient_session_required is True
    denied = bind_actor_identity(
        replace,
        FunctionCallRequest(
            function="strategy.doc.replace",
            actor=ActorContext(session_id=""),
            target=TargetRef(kind="global"),
            payload={},
        ),
        ambient_session_id="",
    )
    assert denied.error is not None
    assert denied.error.error is not None
    assert denied.error.error.code == "actor_session_missing"


def test_scratch_entry_target_kinds_and_claim_required_kind() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("scratch.dispatch_inputs")
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.claim_required_kind is None
    assert entry.owner_module == "yoke_core.domain.project_scratch_dir"
    assert entry.adapter_status == "live"
    assert entry.stability == "stable"
    assert entry.side_effects == ()
    assert entry.emitted_event_names == ()


def test_domain_registrars_includes_register_scratch_module() -> None:
    """Defense in depth — the spec warns that adding only the import
    leaves the new registrar as dead-code. Both edits must land together."""

    from yoke_core.domain.handlers import _register_scratch

    assert _register_scratch in init_register._DOMAIN_REGISTRARS


def test_domain_registrars_includes_register_hooks_module() -> None:
    from yoke_core.domain.handlers import _register_hooks

    assert _register_hooks in init_register._DOMAIN_REGISTRARS


def test_ouroboros_field_note_read_handlers_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "ouroboros.field_note.list" in ids
    assert "ouroboros.field_note.get" in ids


def test_projects_list_handler_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "projects.list" in ids


def test_projects_resolve_by_github_repo_handler_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "projects.resolve_by_github_repo" in ids


def test_shepherd_dependency_write_handlers_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {
        "shepherd.dependency_add.run",
        "shepherd.dependency_update.run",
        "shepherd.dependency_remove.run",
        "shepherd.verdict.run",
        "shepherd.caveat_disposition.run",
    } <= ids


def test_qa_requirement_waive_handler_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "qa.requirement.waive" in ids


def test_register_all_handlers_includes_session_orchestration_family() -> None:
    init_register.register_all_handlers()

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {
        "sessions.touch",
        "sessions.checkpoint",
        "sessions.checkpoint_read",
        "sessions.offer",
        "sessions.ownership_guard",
        "charge.schedule",
    } <= ids

    offer = yoke_function_registry.lookup("sessions.offer")
    assert offer is not None
    assert offer.target_kinds == ("global",)
    assert offer.adapter_status == "live"
    assert offer.ambient_session_required is True

    guard = yoke_function_registry.lookup("sessions.ownership_guard")
    assert guard is not None
    assert guard.target_kinds == ("item",)
    assert guard.claim_required_kind is None

    schedule = yoke_function_registry.lookup("charge.schedule")
    assert schedule is not None
    assert schedule.target_kinds == ("global",)
    assert schedule.ambient_session_required is False

    from yoke_core.domain.handlers import _register_sessions

    assert _register_sessions in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_includes_project_install_family() -> None:
    init_register.register_all_handlers()

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {"project.install.run", "project.refresh.run",
            "project.uninstall.run"} <= ids


def test_product_project_onboarding_writes_skip_harness_session_gate() -> None:
    init_register.register_all_handlers()

    for function_id in (
        "projects.create",
        "projects.update",
        "projects.capability_secret.set",
    ):
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None
        assert entry.ambient_session_required is False


def test_register_all_handlers_includes_project_snapshot_sync() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("project.snapshot.sync")
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.side_effects == ("path_snapshot_write", "path_target_write")
    assert entry.adapter_status == "live"
    assert entry.ambient_session_required is False
    from yoke_core.domain.handlers import _register_project_snapshot

    assert _register_project_snapshot in init_register._DOMAIN_REGISTRARS


def test_onboard_checklist_init_registered() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("onboard.checklist.init")
    assert entry is not None
    assert entry.side_effects == ("db_write",)
    assert entry.ambient_session_required is False
    from yoke_core.domain.handlers import _register_onboard_checklist

    assert _register_onboard_checklist in init_register._DOMAIN_REGISTRARS


def test_onboard_checklist_run_registered_with_dispatch_event_linkage() -> None:
    from yoke_core.domain import project_onboarding_runs

    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup(project_onboarding_runs.OPERATION_RUN)
    assert entry is not None
    assert entry.side_effects == ("db_write",)
    assert entry.ambient_session_required is False
    assert entry.emitted_event_names == ("YokeFunctionCalled",)

    # No onboarding-specific event helper exists yet; registration stays
    # honest that the dispatcher-level YokeFunctionCalled event is the
    # event linkage for this DB-backed checklist mutation.
    assert "OnboardingChecklist" not in entry.emitted_event_names


def test_register_all_handlers_includes_github_pr_create() -> None:
    init_register.register_all_handlers()

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "github.pr.create" in ids
    from yoke_core.domain.handlers import _register_github

    assert _register_github in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_includes_github_actions_runners_status() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("github_actions.runners.status")
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.ambient_session_required is True
    from yoke_core.domain.handlers import _register_github_actions

    assert _register_github_actions in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_includes_items_github_sync() -> None:
    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup("items.github_sync")
    assert entry is not None
    assert entry.target_kinds == ("item",)
    assert entry.claim_required_kind is None
    assert "allow_unclaimed_ownership_guard" in entry.guardrails
    from yoke_core.domain.handlers import _register_items_github_sync

    assert _register_items_github_sync in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_includes_packs_family() -> None:
    init_register.register_all_handlers()

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {
        "packs.list",
        "packs.bundle.get",
        "packs.project.report",
        "packs.get.run",
        "packs.relink.run",
        "packs.update.run",
    } <= ids
    from yoke_core.domain.handlers import _register_packs

    assert _register_packs in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_includes_db_read() -> None:
    from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID

    init_register.register_all_handlers()

    entry = yoke_function_registry.lookup(DB_READ_FUNCTION_ID)
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.ambient_session_required is False
    from yoke_core.domain.handlers import _register_db_read

    assert _register_db_read in init_register._DOMAIN_REGISTRARS


def test_register_all_handlers_is_idempotent() -> None:
    init_register.register_all_handlers()
    first_ids = sorted(
        entry.function_id for entry in yoke_function_registry.list_entries()
    )
    init_register.register_all_handlers()
    second_ids = sorted(
        entry.function_id for entry in yoke_function_registry.list_entries()
    )

    assert first_ids == second_ids


class _RegistrarRaceRequest(BaseModel):
    pass


class _RegistrarRaceResponse(BaseModel):
    ok: bool


def _registrar_race_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _registrar_race_kwargs() -> dict[str, object]:
    return {
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.test_registrar_race",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
    }


def test_register_all_handlers_waits_for_in_flight_bootstrap(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowFirstRegistrar:
        @staticmethod
        def register(registry) -> None:
            registry.register(
                "test.first.run",
                _registrar_race_handler,
                _RegistrarRaceRequest,
                _RegistrarRaceResponse,
                **_registrar_race_kwargs(),
            )
            started.set()
            assert release.wait(timeout=2)

    class SecondRegistrar:
        @staticmethod
        def register(registry) -> None:
            registry.register(
                "test.second.run",
                _registrar_race_handler,
                _RegistrarRaceRequest,
                _RegistrarRaceResponse,
                **_registrar_race_kwargs(),
            )

    monkeypatch.setattr(
        init_register,
        "_DOMAIN_REGISTRARS",
        (SlowFirstRegistrar, SecondRegistrar),
    )

    thread = threading.Thread(target=init_register.register_all_handlers)
    thread.start()
    assert started.wait(timeout=2)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    try:
        init_register.register_all_handlers()
    finally:
        release.set()
        timer.cancel()
        thread.join(timeout=2)

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {"test.first.run", "test.second.run"} <= ids
    assert not thread.is_alive()
