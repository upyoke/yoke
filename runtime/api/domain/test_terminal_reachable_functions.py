"""Every function a person reaches without a session must declare it.

The registry's session requirement is declared once per function, and
the declaration a live install found missing was on the last write of
its onboarding Apply. This contract is the reader that knows which
functions a person without a harness session actually reaches, so a
missing declaration fails here rather than on a stranger's machine.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import terminal_reachable_functions as contract
from yoke_core.domain.function_authz_scope_release_ci import RELEASE_CI_AUTHZ_BY_ID
from yoke_core.domain.function_authz_scope import classify, permission_key_for
from yoke_core.domain.function_authz_types import DENY
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_actor_identity import (
    bind_actor_identity,
    is_read_only,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry, lookup


def _registry_lookup():
    register_all_handlers()
    return lookup


def test_every_terminal_reachable_function_is_session_optional():
    findings = contract.undeclared_terminal_reachable(_registry_lookup())
    assert findings == (), "\n".join(f"{fid}: {why}" for fid, why in findings)


def test_the_surfaces_are_disjoint_from_neither_and_named():
    for function_id in contract.TERMINAL_REACHABLE_FUNCTION_IDS:
        assert contract.surface_for(function_id)


def test_the_onboarding_apply_stage_that_stopped_a_live_install_is_covered():
    # project_structure.patch.apply is the write the wizard's final Apply
    # stage makes; harness.machine_report.upsert is the next one install
    # reaches, and it failed soft, so its loss was silent.
    assert "project_structure.patch.apply" in contract.ONBOARDING_APPLY
    assert "harness.machine_report.upsert" in contract.ONBOARDING_APPLY


def test_release_ci_cancel_is_session_optional_in_the_registry():
    # The release bridge cancels the promotion it dispatched from GitHub
    # Actions, where only a release token authenticates the call.
    entry = _registry_lookup()("github_actions.run.cancel")
    assert entry is not None
    assert entry.ambient_session_required is False


def test_every_mutating_release_ci_function_is_session_optional():
    lookup = _registry_lookup()
    mutating = sorted(
        function_id
        for function_id in RELEASE_CI_AUTHZ_BY_ID
        if not is_read_only(lookup(function_id))
    )
    assert "github_actions.run.cancel" in mutating
    assert set(mutating) <= contract.RELEASE_CI_IDENTITY
    assert contract.undeclared_terminal_reachable(lookup, ids=mutating) == ()


def test_release_ci_cancel_binds_without_any_session():
    entry = _registry_lookup()("github_actions.run.cancel")
    # The https boundary passes the token's actor and an empty envelope
    # session; an actor the envelope names is kept as-is.
    request = FunctionCallRequest(
        function="github_actions.run.cancel",
        actor=ActorContext(actor_id="7", session_id=""),
        target=TargetRef(kind="global"),
        payload={"repo": "upyoke/platform", "run_id": "1"},
    )
    result = bind_actor_identity(entry, request, ambient_session_id="")
    assert result.error is None
    assert result.bound_request is not None
    assert result.bound_request.actor.actor_id == "7"


def test_no_terminal_reachable_function_is_denied_by_default():
    """Binding an actor turns the permission gate on for these calls.

    An unclassified side-effecting function fails closed, so a function
    that reached the handler unbound before would start refusing the
    moment its terminal caller acquired an actor. The classification is
    what keeps that from being the fix's own regression.
    """
    lookup = _registry_lookup()
    denied = []
    for function_id in sorted(contract.TERMINAL_REACHABLE_FUNCTION_IDS):
        entry = lookup(function_id)
        assert entry is not None, function_id
        spec = classify(
            function_id,
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        if spec.scope == DENY:
            denied.append(function_id)
    assert denied == []


def test_a_session_requiring_declaration_is_reported_with_its_surface():
    def _lookup(function_id):
        return RegistryEntry(
            function_id=function_id,
            handler=lambda request: None,
            request_model=type("R", (), {}),
            response_model=type("R", (), {}),
            stability="stable",
            owner_module="test",
            target_kinds=("global",),
            side_effects=("write",),
            emitted_event_names=(),
            guardrails=(),
            adapter_status="live",
            ambient_session_required=True,
        )

    findings = contract.undeclared_terminal_reachable(
        _lookup, ids=["project_structure.patch.apply"]
    )
    assert len(findings) == 1
    function_id, why = findings[0]
    assert function_id == "project_structure.patch.apply"
    assert "onboarding Apply" in why
    assert "ambient_session_required=False" in why


def test_a_read_only_entry_needs_no_declaration():
    def _lookup(function_id):
        return RegistryEntry(
            function_id=function_id,
            handler=lambda request: None,
            request_model=type("R", (), {}),
            response_model=type("R", (), {}),
            stability="stable",
            owner_module="test",
            target_kinds=("global",),
            side_effects=(),
            emitted_event_names=(),
            guardrails=(),
            adapter_status="live",
            ambient_session_required=True,
        )

    assert contract.undeclared_terminal_reachable(
        _lookup, ids=["github_actions.wait_run"]
    ) == ()


def test_a_contract_id_nobody_registers_is_a_finding_too():
    findings = contract.undeclared_terminal_reachable(
        lambda _function_id: None, ids=["items.create"]
    )
    assert len(findings) == 1
    assert "not registered" in findings[0][1]
