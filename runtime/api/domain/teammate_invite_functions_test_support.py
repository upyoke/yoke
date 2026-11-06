# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from runtime.api.fixtures.actor_roles import seed_org_role

from runtime.api.domain.teammate_invite_codes_test_support import _counts as _counts

import json

import logging

from datetime import timedelta

from unittest.mock import Mock

import psycopg

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.server_mode import SERVER_MODE_ENV

from yoke_contracts.timestamps import temporal_wire, utc_now

from yoke_core.api import oidc_config

from yoke_core.api.observability import service_name

from yoke_core.api.observability_debug import (
    DEBUG_MAX_RECORDS_ENV,
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    reset_debug_state,
)

from yoke_core.domain import teammate_invite_codes as invites

from yoke_core.domain import universe_startup_lock

from yoke_core.domain import yoke_function_dispatch_events as events

from yoke_core.domain import yoke_function_registry as registry

from yoke_core.domain.actor_permissions import (
    seed_roles_and_permissions,
)

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.external_identities import default_org_id

from yoke_core.domain.handlers import _register_teammate_invites, identity_invites

from yoke_core.domain.yoke_function_dispatch import dispatch


def _mode(monkeypatch, mode="self-host", oidc="none"):
    monkeypatch.setattr(
        universe_startup_lock,
        "hosted_tenant_container_process",
        lambda: mode == "hosted",
    )
    monkeypatch.setattr(
        identity_invites, "hosted_tenant_container_process", lambda: mode == "hosted"
    )
    monkeypatch.delenv(SERVER_MODE_ENV, raising=False)
    if mode != "local":
        monkeypatch.setenv(SERVER_MODE_ENV, "self-host")
    for key in vars(oidc_config):
        if key.endswith("_ENV"):
            monkeypatch.delenv(getattr(oidc_config, key), raising=False)
    if oidc != "none":
        monkeypatch.setenv(oidc_config.OIDC_ISSUER_ENV, "https://identity.example")
    if oidc == "complete":
        monkeypatch.setenv(oidc_config.OIDC_CLIENT_ID_ENV, "client")
        monkeypatch.setenv(oidc_config.OIDC_CLIENT_SECRET_ENV, "test-secret")
        monkeypatch.setenv(oidc_config.OIDC_REDIRECT_URL_ENV, "https://team.example")


@pytest.fixture
def calls(test_db, monkeypatch, caplog):
    _mode(monkeypatch)
    seed_roles_and_permissions(test_db)
    admin = seed_human_actor(test_db, "Admin")
    seed_org_role(
        test_db, actor_id=admin, org_id=default_org_id(test_db), role_name="admin"
    )
    registry.reset_registry_for_tests()
    _register_teammate_invites.register(registry)
    emitted = Mock(wraps=events.emit_event)
    monkeypatch.setattr(events, "emit_event", emitted)
    monkeypatch.setenv(DEBUG_SCOPE_ENV, f"service:{service_name()}")
    monkeypatch.setenv(DEBUG_UNTIL_ENV, (utc_now() + timedelta(hours=1)).isoformat())
    monkeypatch.setenv(DEBUG_MAX_RECORDS_ENV, "100")
    caplog.set_level(logging.DEBUG, logger="yoke_core")
    reset_debug_state()
    try:
        yield admin, emitted
    finally:
        reset_debug_state()
        registry.reset_registry_for_tests()


def _request(actor, operation, payload=None, request_id=None):
    return FunctionCallRequest(
        function=f"teammate_invites.{operation}",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=str(actor), session_id=""),
        payload=payload or {},
        request_id=request_id,
    )


def _dispatch(actor, operation, payload=None, request_id=None):
    return dispatch(
        _request(actor, operation, payload, request_id), ambient_session_id=""
    )
