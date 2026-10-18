"""Serving mode forms, refusal guidance and invite registration contracts."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS
from yoke_contracts.registered_reads import READ_FUNCTION_IDS
from yoke_core.api import oidc_config
from yoke_core.domain import teammate_invite_codes as invites
from yoke_core.domain import yoke_function_registry as registry
from yoke_core.domain.handlers import identity_invites
from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from runtime.api.domain.test_teammate_invite_functions import (
    _counts,
    _dispatch,
    _mode,
    _request,
)
from runtime.api.domain.test_teammate_invite_functions import calls as calls


@pytest.mark.parametrize(
    "mode,oidc,form,method",
    [
        ("hosted", "none", "email", "yoke_account"),
        ("hosted", "partial", "email", "yoke_account"),
        ("self-host", "complete", "email", "company_sign_in"),
        ("self-host", "none", "name", "invite_code"),
        ("local", "none", "local", "local"),
        ("local", "partial", "local", "local"),
    ],
)
def test_list_reports_form_from_serving_mode_inputs(
    calls, monkeypatch, mode, oidc, form, method
):
    _mode(monkeypatch, mode, oidc)
    resolve = Mock(wraps=oidc_config.resolve_oidc_config)
    monkeypatch.setattr(oidc_config, "resolve_oidc_config", resolve)
    result = _dispatch(calls[0], "list")
    assert result.success, result.error
    assert result.result == {
        "invite_form": form,
        "sign_in_method": method,
        "invites": [],
    }
    assert resolve.call_count == int(mode == "self-host")


@pytest.mark.parametrize("operation", ["list", "create", "identity"])
def test_partial_company_sign_in_refuses_without_writes(
    test_db, calls, monkeypatch, operation
):
    _mode(monkeypatch, oidc="partial")
    before = _counts(test_db)
    if operation == "identity":
        outcome = identity_invites.handle_identity_invite_create(
            _request(calls[0], "create", {"email": "ana@example.com"}),
        )
        error = outcome.error
    else:
        error = _dispatch(
            calls[0], operation, {"name": "Ana"} if operation == "create" else {}
        ).error
    assert error.code == "oidc_misconfigured"
    assert error.message.endswith(
        "ask the server operator to correct company sign-in settings"
    )
    with pytest.raises(invites.TeammateInviteError) as caught:
        invites.invite_form_fact()
    assert caught.value.status == 503 and caught.value.detail == error.message
    assert _counts(test_db) == before
    assert test_db.execute("SELECT count(*) FROM actor_invites").fetchone()[0] == 0


@pytest.mark.parametrize(
    "mode,oidc,error,method",
    [
        ("hosted", "partial", "invite_email_required", "Yoke account"),
        ("self-host", "complete", "invite_email_required", "company sign-in"),
        ("local", "partial", "invite_local_universe", "reachable here only"),
    ],
)
def test_wrong_form_names_method_and_recovery(
    calls, monkeypatch, mode, oidc, error, method
):
    _mode(monkeypatch, mode, oidc)
    refused = _dispatch(calls[0], "create", {"name": "Ana"})
    assert refused.error.code == error and method in refused.error.message
    assert (
        "email" if error == "invite_email_required" else "yoke self-host init"
    ) in refused.error.message


def test_email_invite_requires_name_on_code_server_and_preserves_hosted_refusals(
    calls, monkeypatch
):
    request = _request(calls[0], "create", {"email": "ana@example.com"})
    outcome = identity_invites.handle_identity_invite_create(request)
    assert outcome.error.code == "invite_name_required"
    assert (
        "invite codes" in outcome.error.message
        and "enter their name instead" in outcome.error.message
    )
    _mode(monkeypatch, "hosted", "partial")
    for handler in (
        identity_invites.handle_identity_invite_create,
        identity_invites.handle_identity_invite_list,
        identity_invites.handle_identity_invite_revoke,
    ):
        assert handler(request).error.code == "hosted_invites_platform_owned"


def test_registration_models_floors_and_telemetry():
    registry.reset_registry_for_tests()
    try:
        register_all_handlers()
        for operation in ("create", "list", "revoke", "reissue"):
            function = f"teammate_invites.{operation}"
            entry = registry.lookup(function)
            assert (
                entry.adapter_status == "internal"
                and not entry.ambient_session_required
            )
            assert (
                entry.minimum_serving_version
                == FUNCTION_MINIMUM_SERVING_VERSIONS[function]
                == "next-release"
            )
            assert entry.emitted_event_names == ("YokeFunctionCalled",)
            assert (
                entry.target_kinds == ("global",) and entry.claim_required_kind is None
            )
            assert (function in READ_FUNCTION_IDS) == (operation == "list")
            if operation in {"create", "reissue"}:
                assert {"handler_managed_idempotency", "one_time_secret_result"} <= set(
                    entry.guardrails
                )
            with pytest.raises(ValidationError):
                entry.request_model.model_validate({"unexpected": "field"})
    finally:
        registry.reset_registry_for_tests()
