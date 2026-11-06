# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import hashlib

from contextlib import contextmanager

from datetime import timedelta

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection

from runtime.api.domain.machine_registry_test_support import MACHINE_ID

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_contracts.timestamps import format_instant, utc_now

from yoke_core.domain import machine_authorization_codes as codes

from yoke_core.domain import machine_authorization_decisions as decisions

from yoke_core.domain.auth_schema import create_auth_tables

from yoke_core.domain.external_identity_schema import create_external_identity_tables

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.handlers.machine_authorization_handoff import handle_handoff

from yoke_core.domain.machine_authorization_handoff import handoff

from yoke_core.domain.machine_authorization_schema import (
    create_machine_authorization_table,
)

from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission

from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        create_auth_tables(value)
        create_external_identity_tables(value)
        ensure_machine_registry_schema(value)
        create_machine_authorization_table(value)
        value.execute(
            "INSERT INTO organizations (id,slug,name,created_at) VALUES (2, 'chosen', 'Chosen', 'now')"
        )
        value.execute("INSERT INTO actor_org_roles VALUES (6, 2, 5, 'now')")
        value.execute("INSERT INTO actor_org_roles VALUES (1, 2, 4, 'now')")
        value.commit()
        yield value


@pytest.fixture()
def registry():
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def payload(**updates):
    return {
        "device_code_sha256": hashlib.sha256(b"hosted-device-secret").hexdigest(),
        "user_code": "K7F2",
        "machine_id": MACHINE_ID,
        "machine_name": "Laptop",
        "platform": "Linux",
        "expires_at": format_instant(utc_now() + timedelta(minutes=10)),
        "org_id": 2,
        **updates,
    }


def request(body, actor_id=6):
    return FunctionCallRequest.model_validate(
        {
            "function": "machine_authorization.handoff",
            "version": "v1",
            "request_id": "hosted-handoff",
            "actor": {"actor_id": str(actor_id), "session_id": "hosted-service"},
            "target": {"kind": "global"},
            "payload": body,
        }
    )
