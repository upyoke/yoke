"""Hook API companions reached through routes rather than imports."""

HOOK_REGISTRATION_CONTRACTS = (
    (
        "hook_registration_route_contract",
        frozenset({"packages/yoke-core/src/yoke_core/hooks/registration.py"}),
        (
            "runtime/api/test_api_hooks_evaluate_level.py",
            "runtime/api/test_api_hooks_evaluate_route_actor.py",
            "runtime/api/test_api_hooks_evaluate_server_guardrails.py",
            "runtime/api/test_api_hooks_session_registration.py",
            "runtime/api/test_machine_scope_hook_context.py",
            "runtime/api/test_api_hooks_evaluate_route.py",
        ),
    ),
)
