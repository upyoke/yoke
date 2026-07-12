"""HTTP-boundary authorization for service-only function calls."""

from __future__ import annotations

from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.api.routes.functions import _service_token_guard_response
from yoke_core.domain.api_tokens import INITIAL_ADMIN_TOKEN_NAME
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests


def _auth(token_name: str) -> HttpAuthContext:
    return HttpAuthContext(token_id=1, actor_id=1, token_name=token_name)


def test_lifecycle_refuses_an_ordinary_doorman_token() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        entry = lookup("projects.github_binding.lifecycle")
        denial = _service_token_guard_response(
            {
                "function": "projects.github_binding.lifecycle",
                "version": "v1",
                "request_id": "delivery-1",
            },
            entry,
            _auth("doorman:user-7"),
        )
        assert denial is not None
        assert denial.success is False
        assert denial.error is not None
        assert denial.error.code == "permission_denied"
    finally:
        reset_registry_for_tests()


def test_lifecycle_accepts_the_hosted_service_token() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        entry = lookup("projects.github_binding.lifecycle")
        assert _service_token_guard_response(
            {"function": "projects.github_binding.lifecycle"},
            entry,
            _auth(INITIAL_ADMIN_TOKEN_NAME),
        ) is None
    finally:
        reset_registry_for_tests()


def test_guard_does_not_restrict_normal_project_binding() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        entry = lookup("projects.github_binding.bind")
        assert _service_token_guard_response(
            {"function": "projects.github_binding.bind"},
            entry,
            _auth("doorman:user-7"),
        ) is None
    finally:
        reset_registry_for_tests()
