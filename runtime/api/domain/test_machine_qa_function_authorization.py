from __future__ import annotations

from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.function_authz_scope import PROJECT, classify


def test_baseline_group_two_phase_functions_keep_item_claim_guardrails() -> None:
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import (
        lookup,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    try:
        register_all_handlers()
        direct = lookup("test_machine.baseline_group_execute")
        begin = lookup("test_machine.baseline_group.begin")
        submit = lookup("test_machine.baseline_group.submit")
        abort = lookup("test_machine.baseline_group.abort")
        assert all(entry is not None for entry in (direct, begin, submit, abort))
        assert all(
            entry.target_kinds == ("qa_requirement",)
            and entry.claim_required_kind == "item"
            and entry.adapter_status == "internal"
            for entry in (direct, begin, submit, abort)
        )
        assert direct.guardrails == ("credential_owning_client_required",)
        assert "server_discovered_baseline_group" in begin.guardrails
        assert "lease_waiting_state" in begin.guardrails
        assert "immutable_case_context" in submit.guardrails
        assert "actor_owned_lease" in abort.guardrails
    finally:
        reset_registry_for_tests()


def test_machine_case_two_phase_is_project_write_authorized() -> None:
    for function_id in (
        "test_machine.case.begin",
        "test_machine.case.submit",
        "test_machine.case.abort",
    ):
        spec = classify(
            function_id,
            side_effects=True,
            project_permission=None,
        )
        assert (spec.scope, spec.permission_key) == (
            PROJECT,
            PERM_ITEMS_WRITE,
        )
